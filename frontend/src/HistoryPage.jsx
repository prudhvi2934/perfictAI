/**
 * HistoryPage — shows every reviewed (approved) transaction plus a
 * month-by-month credit/debit summary.
 *
 * Two API calls run when the page loads:
 *   /api/transactions/summary/monthly — per-month credit, debit and net totals
 *   /api/transactions/history         — the full list of approved transactions
 */

import { useState, useEffect } from 'react'
import './HistoryPage.css'

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })

// Turn "2026-06" into "June 2026" for the summary card headings.
function monthLabel(yyyyMm) {
  const [year, month] = yyyyMm.split('-')
  const date = new Date(Number(year), Number(month) - 1)
  return date.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })
}

export default function HistoryPage({ userId }) {
  const [transactions, setTransactions] = useState([])
  const [months, setMonths] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function fetchHistory() {
      setLoading(true)
      setError(null)
      try {
        const [histRes, summaryRes] = await Promise.all([
          fetch(`/api/transactions/history?user_id=${userId}`),
          fetch(`/api/transactions/summary/monthly?user_id=${userId}`),
        ])
        if (!histRes.ok) throw new Error(`Server error: ${histRes.status}`)
        if (!summaryRes.ok) throw new Error(`Server error: ${summaryRes.status}`)
        const hist = await histRes.json()
        const summary = await summaryRes.json()
        setTransactions(hist.transactions)
        setMonths(summary.months)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchHistory()
  }, [userId])

  if (loading) return <p className="status-msg">Loading history...</p>
  if (error)   return <p className="status-msg error">Error: {error}</p>

  return (
    <div className="page">
      <header className="page-header">
        <h1>Transaction History</h1>
        <span className="badge">{transactions.length} reviewed</span>
      </header>

      {/* Monthly credit/debit summary cards */}
      {months.length > 0 && (
        <div className="month-grid">
          {months.map(m => (
            <div className="month-card" key={m.month}>
              <h2 className="month-name">{monthLabel(m.month)}</h2>
              <div className="month-row">
                <span>Credit</span>
                <span className="amount-credit">{inr.format(m.credit)}</span>
              </div>
              <div className="month-row">
                <span>Debit</span>
                <span className="amount-debit">{inr.format(m.debit)}</span>
              </div>
              <div className="month-row month-net">
                <span>Net</span>
                <span className={m.net >= 0 ? 'amount-credit' : 'amount-debit'}>
                  {inr.format(m.net)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {transactions.length === 0 ? (
        <p className="status-msg">No reviewed transactions yet.</p>
      ) : (
        <table className="history-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Merchant</th>
              <th>Type</th>
              <th>Bucket</th>
              <th className="col-amount">Amount</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map(txn => (
              <tr key={txn.id}>
                <td>{txn.date}</td>
                <td>{txn.merchant || '(unknown)'}</td>
                <td><span className="pill pill-type">{txn.transaction_type}</span></td>
                <td><span className="pill pill-bucket">{txn.bucket || 'unknown'}</span></td>
                <td className={`col-amount ${txn.transaction_type === 'credit' ? 'amount-credit' : 'amount-debit'}`}>
                  {txn.transaction_type === 'credit' ? '+' : '−'}{inr.format(txn.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
