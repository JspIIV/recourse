#!/usr/bin/env bash
# One job from fee to payout, with the balances read before and after.
#
# The claim this project makes is that contesting the work moves the money, so
# the test is the claim: open a job with a real fee, deliver something that does
# not do the brief, contest it, and show the client's balance restored and the
# escrow at zero. Anything less is a screenshot of a verdict.
#
# Studionet, because value transfers work there. On testnet-asimov emit_transfer
# records a payout and leaves balances untouched, measured across two
# deployments, so a contract whose point is that money moves cannot show it.
#
# Usage: ./lifecycle.sh 0xCONTRACT
set -u

C="${1:?usage: lifecycle.sh 0xCONTRACT}"
GL="npx genlayer"
RPC="https://studio.genlayer.com/api"

CLIENT=0x80519c53f10d731e4ff83a7d9acd69cf98da6258
WORKER=0x0b57877ec84d96b672cd47d8ea4424283fdb9f6c

bal() {  # bal <address> -> wei
  curl -s -m 30 -X POST "$RPC" -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBalance\",\"params\":[\"$1\",\"latest\"]}" |
    python -c "import sys,json; r=json.load(sys.stdin).get('result'); print(int(r,16) if r else 0)"
}
gen() { python -c "print('%.4f' % (int('$1')/1e18))"; }

send() {  # send <account> <method> <args...>
  local who="$1"; shift
  local method="$1"; shift
  $GL account use "$who" >/dev/null 2>&1
  for attempt in 1 2 3 4 5 6; do
    out=$($GL write "$C" "$method" --args "$@" 2>&1)
    echo "$out" | grep -qE "0x[a-f0-9]{64}" && return 0
    case "$out" in
      *-32005*|*"at capacity"*) echo "    node at capacity, waiting 45s"; sleep 45;;
      *) sleep 20;;
    esac
  done
  echo "    could not send $method"; return 1
}

pay() {  # pay <account> <wei> <method> <args...>
  local who="$1"; shift
  local value="$1"; shift
  local method="$1"; shift
  $GL account use "$who" >/dev/null 2>&1
  for attempt in 1 2 3 4 5 6; do
    out=$($GL write "$C" "$method" --value "$value" --args "$@" 2>&1)
    echo "$out" | grep -qE "0x[a-f0-9]{64}" && return 0
    case "$out" in
      *-32005*|*"at capacity"*) echo "    node at capacity, waiting 45s"; sleep 45;;
      *) echo "$out" | tail -3; sleep 20;;
    esac
  done
  echo "    could not send $method"; return 1
}

wait_status() {  # wait_status <job> <status>
  for _ in $(seq 1 18); do
    $GL call "$C" job --args "$1" 2>/dev/null | grep -q "\"status\": \"$2\"" && return 0
    sleep 20
  done
  return 1
}

FEE=100000000000000000   # 0.1 GEN

echo "before"
C0=$(bal $CLIENT); W0=$(bal $WORKER)
echo "  client $(gen $C0) GEN   worker $(gen $W0) GEN"

echo
echo "1. the client opens a job and locks 0.1 GEN"
pay padv "$FEE" open_job "$WORKER" "Summarise the escrow contract" \
  "Read the escrow contract and list, in plain sentences, every path by which money can leave it and who is allowed to trigger each one." || exit 1
wait_status 0 OPEN || { echo "job never opened"; exit 1; }
echo "  escrow now $($GL call "$C" job --args 0 2>/dev/null | grep -o '"escrow_wei": "[0-9]*"')"

echo
echo "2. the worker delivers something that does not do the brief"
send ppub deliver 0 "Looks fine, no issues found." || exit 1
wait_status 0 DELIVERED || { echo "delivery never landed"; exit 1; }

echo
echo "3. the client contests it, and the round decides the money"
for attempt in 1 2 3 4 5 6; do
  send padv dispute 0 "The delivery is one line and lists no paths at all; it does not answer the brief." || continue
  sleep 30
  out=$($GL call "$C" job --args 0 2>/dev/null | grep -o "{.*}")
  case "$out" in
    *REFUNDED*|*RELEASED*) echo "$out" | python -c "
import sys, json
d = json.loads(sys.stdin.read())
print('  ruling  ', d['ruling'])
print('  status  ', d['status'])
print('  reason  ', d['reason'][:150])
"; break;;
    *) echo "  no ruling yet, attempt $attempt";;
  esac
done

echo
echo "after"
C1=$(bal $CLIENT); W1=$(bal $WORKER)
echo "  client $(gen $C1) GEN   worker $(gen $W1) GEN"
python - <<PY
c0, c1, w0, w1, fee = $C0, $C1, $W0, $W1, $FEE
print()
print("  client moved  %+.4f GEN" % ((c1 - c0) / 1e18))
print("  worker moved  %+.4f GEN" % ((w1 - w0) / 1e18))
print("  fee was        %.4f GEN" % (fee / 1e18))
print()
print("  the worker was paid" if w1 > w0 else "  the worker was not paid")
print("  the client got the fee back" if c1 > c0 - fee else "  the client did not get the fee back")
PY

echo
echo "contract: $($GL call "$C" size 2>/dev/null | grep -o '{.*}')"
