import { useState } from 'react'
import ReviewPage from './ReviewPage'
import HistoryPage from './HistoryPage'
import UploadPage from './UploadPage'
import UserPicker from './UserPicker'
import './App.css'

const LS_KEY = 'perfict_user_id'

function readStoredUserId() {
  const parsed = parseInt(localStorage.getItem(LS_KEY), 10)
  return Number.isFinite(parsed) ? parsed : null
}

export default function App() {
  const [userId, setUserId] = useState(readStoredUserId)
  const [page, setPage] = useState('history') // 'review' | 'history' | 'upload'

  function handleSelectUser(id) {
    localStorage.setItem(LS_KEY, String(id))
    setUserId(id)
  }

  return (
    <>
      <header className="app-header">
        <strong className="app-title">PerfictAI</strong>
        <nav className="app-nav">
          <button
            className={page === 'history' ? 'nav-btn active' : 'nav-btn'}
            onClick={() => setPage('history')}
          >
            History
          </button>
          <button
            className={page === 'review' ? 'nav-btn active' : 'nav-btn'}
            onClick={() => setPage('review')}
          >
            Review
          </button>
          <button
            className={page === 'upload' ? 'nav-btn active' : 'nav-btn'}
            onClick={() => setPage('upload')}
          >
            Upload
          </button>
        </nav>
        <UserPicker selectedUserId={userId} onSelect={handleSelectUser} />
      </header>
      {userId === null ? (
        <p className="no-user-msg">Select a user above to get started.</p>
      ) : page === 'review' ? (
        <ReviewPage userId={userId} />
      ) : page === 'history' ? (
        <HistoryPage userId={userId} />
      ) : (
        <UploadPage userId={userId} />
      )}
    </>
  )
}
