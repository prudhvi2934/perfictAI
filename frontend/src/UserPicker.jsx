import { useState, useEffect } from 'react'
import './UserPicker.css'

export default function UserPicker({ selectedUserId, onSelect }) {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/users')
      .then(r => r.json())
      .then(data => { setUsers(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  if (loading) return <span className="user-picker-loading">Loading users…</span>

  return (
    <label className="user-picker">
      Viewing as:
      <select
        value={selectedUserId ?? ''}
        onChange={e => onSelect(Number(e.target.value))}
      >
        <option value="" disabled>— pick a user —</option>
        {users.map(u => (
          <option key={u.id} value={u.id}>{u.name}</option>
        ))}
      </select>
    </label>
  )
}
