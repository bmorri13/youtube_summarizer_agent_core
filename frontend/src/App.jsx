import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

const SUGGESTED_PROMPTS = [
  'What topics have been covered recently?',
  'Summarize the latest video',
  'Which videos discuss AI agents?',
  'What are the key takeaways across all videos?',
]

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  function handlePromptClick(prompt) {
    setInput(prompt)
    inputRef.current?.focus()
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || isLoading) return

    const userMessage = { role: 'user', content: text }
    const updatedMessages = [...messages, userMessage]
    setMessages(updatedMessages)
    setInput('')
    setIsLoading(true)

    const chatMessages = updatedMessages.map(m => ({
      role: m.role,
      content: m.content,
    }))

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: chatMessages, session_id: sessionId }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(err.detail || 'Request failed')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      let sources = []
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6)

          try {
            const event = JSON.parse(jsonStr)

            if (event.type === 'chunk') {
              assistantContent += event.content
              setMessages([
                ...updatedMessages,
                { role: 'assistant', content: assistantContent, sources },
              ])
            } else if (event.type === 'sources') {
              sources = event.sources || []
            } else if (event.type === 'done') {
              if (event.session_id) setSessionId(event.session_id)
            }
          } catch {
            // skip malformed lines
          }
        }
      }

      if (assistantContent) {
        setMessages([
          ...updatedMessages,
          { role: 'assistant', content: assistantContent, sources },
        ])
      }
    } catch (err) {
      setMessages([
        ...updatedMessages,
        { role: 'error', content: err.message },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="chat-container">
      <div className="chat-header">
        <div className="header-content">
          <h1>YouTube Summaries</h1>
          <p>Ask questions about analyzed videos</p>
        </div>
        {messages.length > 0 && (
          <button
            className="new-chat-btn"
            onClick={() => { setMessages([]); setSessionId(null) }}
            title="New conversation"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        )}
      </div>

      {messages.length === 0 && !isLoading ? (
        <div className="empty-state">
          <div className="empty-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <rect x="8" y="12" width="32" height="24" rx="4" stroke="currentColor" strokeWidth="2"/>
              <path d="M20 24l4 3 4-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="18" cy="22" r="1.5" fill="currentColor"/>
              <circle cx="30" cy="22" r="1.5" fill="currentColor"/>
            </svg>
          </div>
          <h2>What would you like to know?</h2>
          <p>Ask me anything about the YouTube videos that have been analyzed.</p>
          <div className="suggested-prompts">
            {SUGGESTED_PROMPTS.map((prompt, i) => (
              <button
                key={i}
                className="prompt-chip"
                onClick={() => handlePromptClick(prompt)}
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="messages">
          {messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} />
          ))}
          {isLoading && messages[messages.length - 1]?.role === 'user' && (
            <div className="message assistant">
              <div className="loading-shimmer">
                <div className="shimmer-line" style={{ width: '80%' }} />
                <div className="shimmer-line" style={{ width: '60%' }} />
                <div className="shimmer-line" style={{ width: '70%' }} />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      <div className="input-area">
        <form onSubmit={handleSubmit}>
          <div className="input-wrapper">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about video summaries..."
              disabled={isLoading}
              autoFocus
            />
            <button type="submit" disabled={isLoading || !input.trim()} aria-label="Send message">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M3 9h12M10 4l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function extractFileName(uri) {
  if (!uri) return uri
  const parts = uri.split('/')
  const fileName = parts[parts.length - 1]
  return fileName.replace(/\.md$/, '').replace(/_/g, ' ')
}

function MessageBubble({ message }) {
  const [showSources, setShowSources] = useState(false)
  const { role, content, sources } = message

  if (role === 'error') {
    return (
      <div className="message error">
        <span className="error-icon">!</span>
        {content}
      </div>
    )
  }

  return (
    <div className={`message ${role}`}>
      {role === 'assistant' ? (
        <div className="markdown-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ inline, className, children, ...props }) {
                return inline ? (
                  <code className="inline-code" {...props}>{children}</code>
                ) : (
                  <pre className="code-block"><code className={className} {...props}>{children}</code></pre>
                )
              },
              a({ href, children, ...props }) {
                return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
              },
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      ) : (
        content
      )}
      {sources && sources.length > 0 && (
        <div className="sources">
          <button className="sources-toggle" onClick={() => setShowSources(!showSources)}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className={`sources-chevron ${showSources ? 'open' : ''}`}>
              <path d="M3 5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {sources.length} source{sources.length !== 1 ? 's' : ''}
          </button>
          {showSources && (
            <div className="sources-list">
              {sources.map((s, i) => (
                <div key={i} className="source-item">
                  <span className="source-name">{extractFileName(s.source_uri)}</span>
                  <span className="source-score">{(s.score * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default App
