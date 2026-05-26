import React, { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard';
import History from './components/History';
import { Database, Activity, LayoutDashboard, Settings, AlertTriangle } from 'lucide-react';
import './index.css';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [updateInfo, setUpdateInfo] = useState(null);

  const [isUpdating, setIsUpdating] = useState(false);

  useEffect(() => {
    // Verificar OTA Updates silenciosamente al abrir la app
    fetch('http://localhost:8000/api/check_updates')
      .then(res => res.json())
      .then(data => {
        if (data.update_available) {
          setUpdateInfo(data);
        }
      })
      .catch(err => console.error('No se pudo comprobar actualizaciones:', err));
  }, []);

  const handleUpdate = async () => {
    setIsUpdating(true);
    try {
      await fetch('http://localhost:8000/api/apply_update', { method: 'POST' });
      // Esperar 5 segundos y recargar la página para cargar la nueva UI y Backend
      setTimeout(() => {
        window.location.reload();
      }, 5000);
    } catch (err) {
      console.error(err);
      setIsUpdating(false);
    }
  };

  return (
    <div className="layout" style={{ flexDirection: 'column' }}>
      
      {/* Banner de Actualización OTA */}
      {updateInfo && (
        <div style={{
          background: '#FFC107',
          color: '#000',
          padding: '12px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          fontWeight: '600',
          boxShadow: '0 4px 12px rgba(255, 193, 7, 0.3)',
          zIndex: 50
        }}>
          <AlertTriangle size={24} />
          <span>⚠️ Hay una nueva versión o arreglo disponible ({updateInfo.remote_version}).</span>
          <button 
            onClick={handleUpdate}
            disabled={isUpdating}
            style={{
              padding: '6px 16px',
              background: '#000',
              color: '#FFC107',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 'bold',
              cursor: isUpdating ? 'wait' : 'pointer'
            }}>
            {isUpdating ? 'Actualizando (Espera 5s)...' : '✨ Instalar Actualización y Reiniciar'}
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Sidebar */}
        <aside className="sidebar">
        <div className="sidebar-logo">
          <Activity size={28} />
          GoWild Scraper
        </div>
        
        <nav style={{ flex: 1 }}>
          <a 
            href="#" 
            className={`nav-link ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={(e) => { e.preventDefault(); setActiveTab('dashboard'); }}
          >
            <LayoutDashboard size={20} />
            Dashboard
          </a>
          <a 
            href="#" 
            className={`nav-link ${activeTab === 'history' ? 'active' : ''}`}
            onClick={(e) => { e.preventDefault(); setActiveTab('history'); }}
          >
            <Database size={20} />
            Historial de Precios
          </a>
        </nav>

        <div style={{ padding: '16px 0', borderTop: '1px solid var(--glass-border)' }}>
          <a href="#" className="nav-link" style={{ color: 'var(--accent-dim)' }}>
            <Settings size={20} />
            Ajustes
          </a>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
          {activeTab === 'dashboard' && <Dashboard />}
          {activeTab === 'history' && <History />}
        </div>
      </main>
      </div>
    </div>
  );
}

export default App;
