import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import StatusPage from './StatusPage.tsx'

// Sem roteador: o nginx devolve o index.html para qualquer caminho, então basta olhar o pathname.
const isStatusPage = window.location.pathname.replace(/\/+$/, '') === '/status'

createRoot(document.getElementById('root')!).render(
  <StrictMode>{isStatusPage ? <StatusPage /> : <App />}</StrictMode>,
)
