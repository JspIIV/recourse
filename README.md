# Recourse

**An escrow where contesting the work actually moves the money.**

* **App:** https://recourse-escrow.vercel.app
* **Contract:** `0xc7aAce456c1B040DA82D97cc26aDe0703A8824a3` on GenLayer Studionet
* Source: [`contracts/recourse.py`](contracts/recourse.py)

---

## The claim, and the proof

Plenty of marketplaces will show you an AI verdict on a dispute. Almost none let
that verdict touch the funds, because the moment it does, every weakness in it
costs somebody real money. A verdict that changes nothing is a decoration. The
only honest test of an arbiter is whether you would let it hold the purse.

So the round's answer **is** the payout. Measured end to end on chain:

| | before | after | moved |
|---|---|---|---|
| client | 667.9000 GEN | 668.0000 GEN | **+0.1000** |
| worker | 137.4467 GEN | 137.4467 GEN | 0 |
| contract | holding 0.1 | holding 0 | escrow emptied |

The brief asked for every path by which money can leave an escrow contract and
who may trigger each. The delivery was "Looks fine, no issues found." The client
contested it. The round ruled **REFUND**, with this reasoning:

> The brief explicitly required listing every path by which money can leave the
> escrow contract and identifying who can trigger each one. The delivery contains
> none of that substance, it is a single line.

Nobody confirmed that afterwards. There is no operator step, because an operator
step would put the party running the market back in the position of deciding,
which is the arrangement this exists to remove.

## Access control, also measured

A dispute sent from an account that was not the client was refused on chain: the
job stayed `DELIVERED` and the 0.1 GEN stayed where it was. Only the client can
contest, only the named worker can deliver, and only the client can accept.

## What goes to consensus, and what does not

**One field.** `RELEASE` or `REFUND`. Every field bound to an equivalence rule
costs agreement: on this network a round binding four fields returned
`NOT_VOTED` six times in a row and completed once a derivable field was removed.
The reasoning is recorded and never compared, because two honest readers word it
differently.

**The amounts are never asked.** The contract computes them from what that job
locked. Asking a model to divide a fee is asking witnesses to agree on arithmetic
the contract can do exactly and for free.

**The complaint is not evidence.** The prompt says so: it is the client's
account, and if it describes a fault that is not actually in the delivery, that
alone is reason to release. Otherwise a client wins by complaining loudly.

**A vague brief is the client's problem.** If the brief was too vague to have
been failed, the ruling is `RELEASE`. The party who wrote an unclear brief
carries that, not the party who worked to it.

## The four rules that keep money safe

**A payable method never raises.** Raising out of one reverts the state change
and keeps the value: measured previously, a refused deposit left the caller
poorer and the contract heavier. Every guard here refuses by paying the value
back and recording why, so a refusal is a successful transaction that created
nothing.

**An unreadable round settles nothing.** Not a default and not a coin flip. The
job stays `DISPUTED` and can be put to the network again. A default would be a
decision nobody made, taken with somebody else's money.

**Settlement cannot run twice.** The amount comes from the escrow entry rather
than the job record, and the entry is cleared before the transfer, so a second
settlement has nothing left to pay.

**Nothing inside the nondeterministic block reads storage or raises.** On chain
id 4221 a round that touches `self.<field>` from inside the block ends
`FINISHED_WITH_ERROR` every time, and a throw there cannot be caught outside: it
reverts the transaction and the fee freezes.

## Why Studionet

On `testnet-asimov`, `emit_transfer` records a payout and leaves balances
untouched, measured across two deployments. A contract whose whole point is that
money moves cannot demonstrate that there, so this runs where the transfer
actually happens rather than showing a payout that is only bookkeeping.

## Interface

| | |
|---|---|
| `open_job(worker, title, asked_for)` | payable. Locks the fee against a brief |
| `deliver(job_id, delivery)` | the named worker hands in the work |
| `accept(job_id)` | the client is satisfied. Pays the worker, no round needed |
| `dispute(job_id, complaint)` | one consensus round decides where the fee goes |
| `job(id)`, `page(start, count)`, `size()` | views |

Accepting deliberately costs no round: asking the network to confirm a payment
both parties already agree on would spend a round for nothing.

## A deployment that reported success and produced nothing

`0xcE4c7B074740830E85022F329231A8CF22707d23` is dead. `gl.evm.contract_interface`
was used as a base class rather than a decorator, so the module never imported.
The CLI reported the deployment as successful and returned an address; reads
against it answered `contract not found`. Check the state, not the label.
