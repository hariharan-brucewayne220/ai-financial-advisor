/**
 * Frontend Entry Point
 *
 * Sets up React with the root dashboard component.
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import Dashboard from '@/components/Dashboard'
import '@/styles/globals.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Dashboard />
  </React.StrictMode>
)
