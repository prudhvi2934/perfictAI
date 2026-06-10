import { useState } from 'react'
import ReviewPage from './ReviewPage'
import UserPicker from './UserPicker'
import './App.css'

const LS_KEY = 'perfict_user_id'

function readStoredUserId() {
  const parsed = parseInt(localStorage.getItem(LS_KEY), 10)
  return Number.isFinite(parsed) ? parsed : null
}

export default function App() {
  const [userId, setUserId] = useState(readStoredUserId)

  function handleSelectUser(id) {
    localStorage.setItem(LS_KEY, String(id))
    setUserId(id)
  }

  return (
    <>
      <header className="app-header">
        <strong className="app-title">PerfictAI</strong>
        <UserPicker selectedUserId={userId} onSelect={handleSelectUser} />
      </header>
      {userId !== null
        ? <ReviewPage userId={userId} />
        : <p className="no-user-msg">Select a user above to get started.</p>
      }
    </>
  )
}
