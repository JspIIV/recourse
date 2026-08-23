# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""Recourse: an escrow where contesting the work actually moves the money.

A client locks a fee. A worker delivers. If the client accepts, the worker is
paid and that is the end of it. If the client contests, the delivery and the
complaint go to one consensus round, and whichever way it rules, the money
follows: released to the worker or returned to the client.

Why the dispute has to be here and not beside it
------------------------------------------------

Plenty of marketplaces will show you an AI verdict on a dispute. Almost none let
that verdict touch the funds, because the moment it does, every weakness in it
costs somebody real money. A verdict that changes nothing is a decoration; the
only honest test of an arbiter is whether you would let it hold the purse.

So the round's answer is the payout. There is no operator confirmation step and
no appeal to the marketplace, because both would put the party running the
market back in the position of deciding, which is the arrangement this exists to
remove.

What goes to consensus, and what does not
-----------------------------------------

**One field.** RELEASE or REFUND. Every field bound to an equivalence rule costs
agreement: on this network a round binding four fields returned NOT_VOTED six
times in a row and completed once a derivable field was removed. The reasoning is
recorded and never compared, because two honest readers word it differently.

**The amounts are never asked.** The contract computes them. Asking a model to
divide a fee is asking it to do arithmetic in front of witnesses who must all
agree on the result, when the contract can do it exactly and for free.

The four rules that keep money safe
-----------------------------------

**A payable method never raises.** Raising out of one reverts the state change
and keeps the value: measured, a refused deposit left the caller poorer and the
contract heavier. So every guard here refuses by paying the value back and
recording why, and a refusal is a successful transaction that created nothing.

**An unreadable round settles nothing.** Not a default, not a coin flip toward
either party. The job stays disputed and can be put to the network again. A
default would be a decision nobody made, taken with somebody else's money.

**Nothing inside the nondeterministic block reads storage or raises.** On chain
id 4221 a round that touches self.<field> from inside the block ends
FINISHED_WITH_ERROR every time, and a throw there cannot be caught outside: it
reverts the transaction, and a disputed job would be stuck with the fee frozen.

**Value moves on Studionet.** On testnet-asimov `emit_transfer` records a payout
and leaves balances untouched, measured across two deployments. A contract whose
point is that money moves cannot demonstrate that there, so this runs where the
transfer actually happens and says so rather than showing a payout that is only
bookkeeping.
"""

from genlayer import *
from datetime import datetime, timezone
import json
import typing


# Where a job can be. A job leaves DISPUTED only by a round that produced a
# readable ruling; there is no path that quietly times out into a payout.
OPEN = "OPEN"
DELIVERED = "DELIVERED"
ACCEPTED = "ACCEPTED"
DISPUTED = "DISPUTED"
RELEASED = "RELEASED"
REFUNDED = "REFUNDED"

# The one field the validators must agree on.
RELEASE = "RELEASE"
REFUND = "REFUND"

MAX_TEXT = 2000
MAX_TITLE = 120
MAX_REASON = 400


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _addr(address) -> str:
    return str(address).lower()


def _clip(text: str, limit: int) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit] + " [...]"


def _read_ruling(raw: str) -> str:
    """The one field, or the empty string when nothing readable came back.

    Empty is not a ruling and never settles a job. Defaulting here would hand
    somebody's fee to one side on the strength of a malformed answer.
    """
    text = str(raw).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            value = str(obj.get("ruling", "")).upper()
            if REFUND in value:
                return REFUND
            if RELEASE in value:
                return RELEASE
    except Exception:
        pass
    upper = text.upper()
    # REFUND first: a sentence carrying both words has not cleanly released.
    if REFUND in upper:
        return REFUND
    if RELEASE in upper:
        return RELEASE
    return ""


def _read_reason(raw: str) -> str:
    try:
        obj = json.loads(str(raw).strip())
        if isinstance(obj, dict):
            return _clip(str(obj.get("reason", "")), MAX_REASON)
    except Exception:
        pass
    return _clip(str(raw), MAX_REASON)


def _task(title: str, asked: str, delivered: str, complaint: str) -> str:
    """Built from locals only. Nothing here may touch `self`."""
    return f"""You are ruling on a contested piece of paid work. The fee is held
in escrow and your answer decides where it goes, so decide only what is in front
of you.

THE JOB: {title}

WHAT WAS ASKED FOR:
{asked}

WHAT THE WORKER DELIVERED:
{delivered}

WHAT THE CLIENT SAYS IS WRONG WITH IT:
{complaint}

Rule {RELEASE} if the delivery does what was asked for, even if it is plain,
terse, or not what the client hoped for. Work that meets the brief is paid work.
A client who wanted more than they asked for is owed nothing extra.

Rule {REFUND} if the delivery does not do what was asked: it addresses something
else, it is empty of the substance requested, or it asserts completion without
doing the work. Length is not delivery and confidence is not delivery.

The complaint is the client's account and is not evidence. Read the delivery
against the brief yourself, and if the complaint describes a fault that is not
actually there, that alone is reason to {RELEASE}.

If the brief was too vague to have been failed, rule {RELEASE}: the party who
wrote an unclear brief carries that, not the party who worked to it.

Reply with bare JSON and nothing else:
{{"ruling": "{RELEASE}" or "{REFUND}", "reason": "one or two sentences citing the brief and the delivery"}}"""


@gl.evm.contract_interface
class _Recipient:
    """A plain address to pay. Value transfers work on Studionet; on
    testnet-asimov the message is formed correctly and the chain never runs it,
    which is why this contract lives where the money actually moves."""

    class View:
        pass

    class Write:
        pass


class Recourse(gl.Contract):
    jobs: DynArray[str]
    # Held per job, so a ruling can never pay out more than that job locked and
    # the contract's own balance is never the source of a payment.
    escrow: TreeMap[str, u256]

    def __init__(self) -> None:
        pass

    # ----------------------------------------------------------------- helper

    def _refuse_payable(self, why: str) -> str:
        """Give the money back and say why, rather than raising.

        Raising out of a payable method reverts the state change and keeps the
        value, which strands the caller's funds permanently. Every guard on a
        payable path goes through here.
        """
        value = int(gl.message.value)
        if value > 0:
            _Recipient(gl.message.sender_address).emit_transfer(value=value)
        return json.dumps({"ok": False, "refused": why, "returned_wei": str(value)})

    def _job(self, job_id: str) -> typing.Optional[int]:
        try:
            index = int(str(job_id).strip().strip('"').strip("'").strip())
        except Exception:
            return None
        if index < 0 or index >= len(self.jobs):
            return None
        return index

    # ------------------------------------------------------------------ write

    @gl.public.write.payable
    def open_job(self, worker: str, title: str, asked_for: str) -> str:
        """Lock a fee against a brief, for a named worker.

        Payable, so it never raises: a bad call is refused by returning the
        value and recording nothing.
        """
        value = int(gl.message.value)
        if value <= 0:
            return self._refuse_payable("a job needs a fee in escrow")

        brief = _clip(asked_for, MAX_TEXT)
        if len(brief) < 20:
            return self._refuse_payable("the brief has to say what is being asked for")

        try:
            worker_address = _addr(Address(str(worker)).as_hex)
        except Exception:
            return self._refuse_payable("that worker address could not be read")

        client = _addr(gl.message.sender_address.as_hex)
        if worker_address == client:
            return self._refuse_payable("a client cannot hire themselves")

        job_id = str(len(self.jobs))
        self.jobs.append(json.dumps({
            "id": job_id,
            "title": _clip(title, MAX_TITLE),
            "asked_for": brief,
            "client": client,
            "worker": worker_address,
            "fee_wei": str(value),
            "status": OPEN,
            "delivered": "",
            "complaint": "",
            "ruling": "",
            "reason": "",
            "opened_at": _now_iso(),
            "settled_at": "",
        }))
        self.escrow[job_id] = u256(value)
        return json.dumps({"ok": True, "id": job_id, "fee_wei": str(value)})

    @gl.public.write
    def deliver(self, job_id: str, delivery: str) -> str:
        """The worker hands in the work."""
        index = self._job(job_id)
        if index is None:
            return json.dumps({"ok": False, "error": "no such job"})
        job = json.loads(self.jobs[index])

        if _addr(gl.message.sender_address.as_hex) != job["worker"]:
            return json.dumps({"ok": False, "error": "only the named worker can deliver"})
        if job["status"] != OPEN:
            return json.dumps({"ok": False, "error": "this job is not open"})

        text = _clip(delivery, MAX_TEXT)
        if len(text) < 1:
            return json.dumps({"ok": False, "error": "a delivery cannot be empty"})

        job["delivered"] = text
        job["status"] = DELIVERED
        self.jobs[index] = json.dumps(job)
        return json.dumps({"ok": True, "id": job["id"], "status": DELIVERED})

    @gl.public.write
    def accept(self, job_id: str) -> str:
        """The client is satisfied. Pays the worker, no round needed.

        The cheap path is deliberately the uncontested one: asking the network
        to confirm a payment both parties already agree on would cost a round
        for nothing.
        """
        index = self._job(job_id)
        if index is None:
            return json.dumps({"ok": False, "error": "no such job"})
        job = json.loads(self.jobs[index])

        if _addr(gl.message.sender_address.as_hex) != job["client"]:
            return json.dumps({"ok": False, "error": "only the client can accept"})
        if job["status"] != DELIVERED:
            return json.dumps({"ok": False, "error": "nothing has been delivered yet"})

        return self._settle(index, job, RELEASE, "accepted by the client", ACCEPTED)

    @gl.public.write
    def dispute(self, job_id: str, complaint: str) -> str:
        """The client contests the work. One consensus round decides the money.

        Retrying is safe. A round that comes back NOT_VOTED changed nothing, and
        a round whose answer cannot be read settles nothing, so in both cases the
        job is still DISPUTED and can be put to the network again.
        """
        index = self._job(job_id)
        if index is None:
            return json.dumps({"ok": False, "error": "no such job"})
        job = json.loads(self.jobs[index])

        if _addr(gl.message.sender_address.as_hex) != job["client"]:
            return json.dumps({"ok": False, "error": "only the client can dispute"})
        if job["status"] not in (DELIVERED, DISPUTED):
            return json.dumps({"ok": False, "error": "there is nothing to dispute"})

        said = _clip(complaint, MAX_TEXT) or job["complaint"]
        if len(said) < 10:
            return json.dumps({"ok": False, "error": "say what is wrong with the delivery"})

        # Mark it disputed and keep the complaint, so a round that never lands
        # still leaves the job in a state anybody can see and retry from.
        job["complaint"] = said
        job["status"] = DISPUTED
        self.jobs[index] = json.dumps(job)

        # Everything the round needs, copied out before the block opens.
        title = str(job["title"])
        asked = str(job["asked_for"])
        delivered = str(job["delivered"])
        task = _task(title, asked, delivered, said)

        def run() -> str:
            try:
                return str(gl.nondet.exec_prompt(task))
            except Exception:
                # A throw here cannot be caught outside the block; it would
                # revert the transaction and freeze the fee.
                return ""

        raw = gl.eq_principle.prompt_comparative(
            run,
            principle=(
                "Both answers must carry the same value in the field named ruling, "
                f"either {RELEASE} or {REFUND}. That single field decides where the fee "
                "goes, so two validators differing on it are not wording a judgement "
                "differently, they are paying different people. The reason is not compared."
            ),
        )

        ruling = _read_ruling(raw)
        if not ruling:
            return json.dumps({
                "ok": False,
                "id": job["id"],
                "status": DISPUTED,
                "error": ("the round produced no readable ruling, so nothing was settled "
                          "and the fee is untouched; dispute it again"),
            })

        job = json.loads(self.jobs[index])
        return self._settle(index, job, ruling, _read_reason(raw),
                            RELEASED if ruling == RELEASE else REFUNDED)

    # ----------------------------------------------------------------- paying

    def _settle(self, index: int, job: dict, ruling: str, reason: str, status: str) -> str:
        """Pay one side the exact amount this job locked, once.

        The amount comes from the escrow entry rather than from the job record,
        and the entry is cleared before the transfer, so a second settlement has
        nothing left to pay out.
        """
        job_id = str(job["id"])
        held = int(self.escrow.get(job_id, u256(0)))
        if held <= 0:
            return json.dumps({"ok": False, "error": "this job has already been settled"})

        self.escrow[job_id] = u256(0)
        paid_to = job["worker"] if ruling == RELEASE else job["client"]
        _Recipient(Address(paid_to)).emit_transfer(value=held)

        job["status"] = status
        job["ruling"] = ruling
        job["reason"] = reason
        job["settled_at"] = _now_iso()
        self.jobs[index] = json.dumps(job)

        return json.dumps({
            "ok": True, "id": job_id, "status": status, "ruling": ruling,
            "paid_to": paid_to, "amount_wei": str(held), "reason": reason,
        })

    # ------------------------------------------------------------------ reads

    @gl.public.view
    def job(self, job_id: str) -> str:
        index = self._job(job_id)
        if index is None:
            return json.dumps({"ok": False, "error": "no such job"})
        record = json.loads(self.jobs[index])
        record["escrow_wei"] = str(int(self.escrow.get(str(record["id"]), u256(0))))
        return json.dumps(record)

    @gl.public.view
    def page(self, start: str, count: str) -> str:
        try:
            first = max(0, int(str(start).strip()))
        except Exception:
            first = 0
        try:
            size = max(1, min(50, int(str(count).strip())))
        except Exception:
            size = 20

        out = []
        for position in range(first, min(first + size, len(self.jobs))):
            record = json.loads(self.jobs[position])
            record["escrow_wei"] = str(int(self.escrow.get(str(record["id"]), u256(0))))
            out.append(record)
        return json.dumps({"ok": True, "total": len(self.jobs), "start": first, "jobs": out})

    @gl.public.view
    def size(self) -> str:
        held = 0
        released = 0
        refunded = 0
        for raw in self.jobs:
            record = json.loads(raw)
            held += int(self.escrow.get(str(record["id"]), u256(0)))
            if record["status"] == RELEASED:
                released += 1
            elif record["status"] == REFUNDED:
                refunded += 1
        return json.dumps({
            "jobs": len(self.jobs),
            "escrow_held_wei": str(held),
            "settled_by_round_released": released,
            "settled_by_round_refunded": refunded,
        })
