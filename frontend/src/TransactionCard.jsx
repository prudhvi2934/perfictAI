/**
 * TransactionCard — one card per pending transaction.
 *
 * Props:
 *   txn       — the transaction object from the backend
 *   onApprove — called with the transaction id after a successful approve
 *
 * Local state:
 *   type   — the transaction_type the user has chosen (pre-filled with AI guess)
 *   bucket — the bucket the user has chosen (pre-filled with AI guess)
 *   saving — true while the approve request is in flight (disables the button)
 *   err    — error message if the approve request failed
 */

import { useState } from 'react'
import './TransactionCard.css'

const TYPES = ['expense', 'investment', 'loan_repayment', 'credit', 'others']
const BUCKETS = ['fundamentals', 'fun', 'future_you', 'unknown']

export default function TransactionCard({ txn, onApprove, userId }) {
  const [type, setType]     = useState(txn.transaction_type || 'others')
  const [bucket, setBucket] = useState(txn.bucket || 'unknown')
  const [saving, setSaving] = useState(false)
  const [err, setErr]       = useState(null)

  async function handleApprove() {
    setSaving(true)
    setErr(null)
    try {
      const res = await fetch(`/api/transactions/${txn.id}/approve?user_id=${userId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transaction_type: type, bucket }),
      })
      if (!res.ok) {
        const detail = await res.json()
        throw new Error(detail.detail || `Server error ${res.status}`)
      }
      // Tell the parent page to remove this card.
      onApprove(txn.id)
    } catch (e) {
      setErr(e.message)
      setSaving(false)
    }
  }

  // Format the amount as Indian rupees (₹1,23,456.00)
  const amount = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
  }).format(txn.amount)

  return (
    <div className="card">
      {/* Top row: merchant + amount */}
      <div className="card-top">
        <span className="merchant">{txn.merchant || '(unknown merchant)'}</span>
        <span className="amount">{amount}</span>
      </div>

      {/* Middle row: date + description */}
      <div className="card-meta">
        <span>{txn.date}</span>
        {txn.description && <span className="desc">{txn.description}</span>}
      </div>

      {/* Controls: dropdowns + approve button */}
      <div className="card-controls">
        <label>
          Type
          <select value={type} onChange={e => setType(e.target.value)}>
            {TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
        </label>

        <label>
          Bucket
          <select value={bucket} onChange={e => setBucket(e.target.value)}>
            {BUCKETS.map(b => <option key={b}>{b}</option>)}
          </select>
        </label>

        <button
          className="approve-btn"
          onClick={handleApprove}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Approve'}
        </button>
      </div>

      {err && <p className="card-error">{err}</p>}
    </div>
  )
}
