/**
 * ReviewPage — shows every pending transaction and lets you approve them.
 *
 * Concepts used here:
 *   useState  — stores data that can change (the list of transactions, loading flag, etc.)
 *   useEffect — runs code once when the page first loads (to fetch transactions from the API)
 *   fetch     — built-in browser function to call the backend
 *   .map()    — turns an array of data objects into an array of React elements
 */

import { useState, useEffect } from 'react'
import TransactionCard from './TransactionCard'
import './ReviewPage.css'

export default function ReviewPage() {
  // `transactions` holds the list we get back from the backend.
  // It starts as an empty array so the page renders without crashing before data arrives.
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // fetchPending asks the backend for all transactions that need review.
  // We define it outside useEffect so we can call it again after an approve action.
  async function fetchPending() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/transactions/pending')
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      const data = await res.json()
      setTransactions(data.transactions)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // useEffect with [] runs fetchPending exactly once — when the page first mounts.
  useEffect(() => {
    fetchPending()
  }, [])

  // onApprove is called by a TransactionCard when the user clicks Approve.
  // We remove that card from local state immediately (optimistic UI) so the page
  // feels fast, instead of re-fetching the whole list.
  function onApprove(approvedId) {
    setTransactions(prev => prev.filter(t => t.id !== approvedId))
  }

  if (loading) return <p className="status-msg">Loading transactions...</p>
  if (error)   return <p className="status-msg error">Error: {error}</p>

  return (
    <div className="page">
      <header className="page-header">
        <h1>Transaction Review</h1>
        <span className="badge">{transactions.length} pending</span>
      </header>

      {transactions.length === 0 ? (
        <p className="status-msg">All caught up — no pending transactions.</p>
      ) : (
        <div className="card-list">
          {transactions.map(txn => (
            // Each card gets the transaction object and a callback for when it's approved.
            <TransactionCard key={txn.id} txn={txn} onApprove={onApprove} />
          ))}
        </div>
      )}
    </div>
  )
}
