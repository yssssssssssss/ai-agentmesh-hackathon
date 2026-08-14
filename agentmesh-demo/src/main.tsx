import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import { DemoProvider } from './store/DemoContext.tsx'
import { SessionProvider } from './store/SessionContext.tsx'
import { ChatProvider } from './store/ChatContext.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <DemoProvider>
          <ChatProvider>
            <App />
          </ChatProvider>
        </DemoProvider>
      </SessionProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
