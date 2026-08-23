// Reading Recourse, and sending the four transactions it takes.
//
// Reading is free and needs no account. Opening a job carries the fee, so it is
// the one call that must go through a wallet with value attached; the CLI cannot
// send `gl.message.value` at all, which is exactly why the funding path lives
// here rather than in a script.
import { createClient } from 'genlayer-js';
import { studionet } from 'genlayer-js/chains';

export const RECOURSE = '0xcE4c7B074740830E85022F329231A8CF22707d23';
export const REPO = 'https://github.com/JspIIV/recourse';
export const CHAIN_ID_HEX = '0xf22f'; // studionet

// A dispute is one prompt over a brief, a delivery and a complaint. Six million
// is well above what it uses; letting the SDK estimate ran out of gas through
// the wallet path on a sibling contract.
const GAS = 6_000_000n;

const STUDIONET = {
  chainId: CHAIN_ID_HEX,
  chainName: 'GenLayer Studionet',
  nativeCurrency: { name: 'GEN', symbol: 'GEN', decimals: 18 },
  rpcUrls: ['https://studio.genlayer.com/api'],
};

export const reader = createClient({ chain: studionet });
export const hasWallet = () => typeof window !== 'undefined' && !!window.ethereum;

export async function read(fn, args = []) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const raw = await reader.readContract({ address: RECOURSE, functionName: fn, args });
      try { return JSON.parse(raw); } catch { return raw; }
    } catch (e) {
      const message = String(e?.message || e);
      if (!/fetch failed|timeout|socket|Rate limit|busy|-32603|-32005|network/i.test(message)) throw e;
      await new Promise((r) => setTimeout(r, 1200 * (attempt + 1)));
    }
  }
  throw new Error('the network did not answer after four attempts');
}

export async function balanceOf(address) {
  const res = await fetch(STUDIONET.rpcUrls[0], {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1, method: 'eth_getBalance', params: [address, 'latest'],
    }),
  });
  const body = await res.json();
  return body.result ? BigInt(body.result) : 0n;
}

// genlayer-js hands the wallet a fully specified legacy transaction carrying
// nonce, gas, gasPrice, type and chainId. Wallets are strict about exactly those
// fields and answer -32602 without saying which one they disliked, which makes a
// working contract look like a broken app. Trim it to what a wallet wants, and
// keep `value`, because on this contract the value is the point.
function walletFriendly(provider) {
  return {
    ...provider,
    request: async (args) => {
      if (args?.method !== 'eth_sendTransaction') return provider.request(args);
      const [tx] = args.params || [];
      const lean = { from: tx.from, to: tx.to, data: tx.data };
      if (tx.value && tx.value !== '0x0') lean.value = tx.value;
      return provider.request({ method: 'eth_sendTransaction', params: [lean] });
    },
  };
}

async function ensureStudionet() {
  const current = await window.ethereum.request({ method: 'eth_chainId' });
  if (String(current).toLowerCase() === CHAIN_ID_HEX) return;
  try {
    await window.ethereum.request({
      method: 'wallet_switchEthereumChain', params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (e) {
    if (Number(e?.code) !== 4902 && !/unrecognized|not been added/i.test(String(e?.message))) throw e;
    await window.ethereum.request({ method: 'wallet_addEthereumChain', params: [STUDIONET] });
  }
}

export async function connect() {
  if (!hasWallet()) throw new Error('No wallet in this browser. MetaMask or any EIP-1193 wallet works.');
  const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
  const account = accounts?.[0];
  if (!account) throw new Error('The wallet returned no account.');
  // Signing on the wrong chain produces a transaction that goes nowhere and an
  // error that blames the contract, so the chain is settled before anything else.
  await ensureStudionet();
  return account;
}

const writer = (account) => createClient({
  chain: studionet, account, provider: walletFriendly(window.ethereum),
});

export const openJob = (account, worker, title, askedFor, feeWei) =>
  writer(account).writeContract({
    address: RECOURSE, functionName: 'open_job', args: [worker, title, askedFor],
    value: feeWei, gas: GAS,
  });

export const deliver = (account, jobId, delivery) => writer(account).writeContract({
  address: RECOURSE, functionName: 'deliver', args: [String(jobId), delivery],
  value: 0n, gas: GAS,
});

export const accept = (account, jobId) => writer(account).writeContract({
  address: RECOURSE, functionName: 'accept', args: [String(jobId)],
  value: 0n, gas: GAS,
});

export const dispute = (account, jobId, complaint) => writer(account).writeContract({
  address: RECOURSE, functionName: 'dispute', args: [String(jobId), complaint],
  value: 0n, gas: GAS,
});

// NOT_VOTED is neither success nor failure: the validators did not complete a
// vote, the contract's state is untouched, and sending the same call again is
// correct and safe. FINISHED_WITH_ERROR is the opposite and must stop the wait.
export async function settle(hash, tick = () => {}) {
  const deadline = Date.now() + 6 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 10_000));
    let receipt;
    try {
      receipt = await reader.getTransaction({ hash });
    } catch {
      tick('waiting for the node');
      continue;
    }
    const status = String(receipt?.statusName || '');
    const execution = String(receipt?.txExecutionResultName || '');
    if (execution === 'FINISHED_WITH_ERROR') {
      return { ok: false, reason: 'The round ended in an error and nothing was settled.' };
    }
    if (execution === 'NOT_VOTED') {
      return {
        ok: false, retryable: true,
        reason: 'The validators did not finish voting. Nothing changed, so trying again is safe.',
      };
    }
    if (execution === 'FINISHED_WITH_RETURN' || status === 'FINALIZED' || status === 'ACCEPTED') {
      return { ok: true };
    }
    tick(status ? status.toLowerCase() : 'in flight');
  }
  return { ok: false, retryable: true, reason: 'Still settling. Reload to see whether it landed.' };
}
