/**
 * UploadPage — upload a bank statement CSV as an alternative to email ingestion.
 *
 * The file is sent to POST /statements/upload, which parses each row, classifies
 * it via the LLM, and stores the results as pending transactions. The response
 * summarises how many were imported vs skipped as duplicates.
 */

import { useState } from 'react'
import './UploadPage.css'

export default function UploadPage({ userId }) {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  function onFileChange(e) {
    setFile(e.target.files[0] ?? null)
    setResult(null)
    setError(null)
  }

  async function onUpload() {
    if (!file) return
    setUploading(true)
    setResult(null)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`/api/statements/upload?user_id=${userId}`, {
        method: 'POST',
        body: form,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `Server error: ${res.status}`)
      setResult(data)
      setFile(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Upload Statement</h1>
      </header>

      <p className="upload-hint">
        Upload a bank statement in CSV format. Each row is classified and added
        to your review queue. Re-uploading the same statement is safe — rows
        already imported are skipped.
      </p>

      <div className="upload-box">
        <input type="file" accept=".csv,text/csv" onChange={onFileChange} />
        <button
          className="upload-btn"
          onClick={onUpload}
          disabled={!file || uploading}
        >
          {uploading ? 'Parsing…' : 'Upload & parse'}
        </button>
      </div>

      {error && <p className="status-msg error">Error: {error}</p>}

      {result && (
        <div className="upload-result">
          <p>
            Parsed <strong>{result.parsed}</strong> transactions —{' '}
            <strong>{result.imported}</strong> imported,{' '}
            <strong>{result.duplicates}</strong> duplicates skipped.
          </p>
          {result.pending_review > 0 && (
            <p>
              {result.pending_review} are waiting for you on the Review page.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
