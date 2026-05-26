import React, { useState, useEffect, useRef } from 'react';
import { Play, Upload, CheckCircle, AlertTriangle, Database } from 'lucide-react';

export default function Dashboard() {
  const [file, setFile] = useState(null);
  const [categoryUrl, setCategoryUrl] = useState('');
  const [scraperType, setScraperType] = useState('sodimac');
  const [status, setStatus] = useState('idle'); // idle, queued, running, finished, error
  const [queuePosition, setQueuePosition] = useState(0);
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({ total_zones: 42, current_zone: 0, skus_found: 0 });
  const [currentJobId, setCurrentJobId] = useState(null);
  const ws = useRef(null);
  const logsEndRef = useRef(null);

  useEffect(() => {
    // Scroll to bottom of terminal
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const startScraping = async () => {
    const isCategoryScraper = scraperType === 'maestra_seccion' || scraperType === 'precios_mayoristas';
    
    if (!isCategoryScraper && !file) return;
    if (isCategoryScraper && !categoryUrl) return;

    setStatus('queued');
    setLogs([]);
    setStats({ total_zones: 42, current_zone: 0, skus_found: 0 });

    const formData = new FormData();
    formData.append('scraper_type', scraperType);
    
    if (isCategoryScraper) {
      formData.append('url', categoryUrl);
    } else {
      formData.append('file', file);
    }

    try {
      // API Call to Backend
      const res = await fetch('http://localhost:8000/api/scrape', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      
      if (data.error) {
        setStatus('error');
        setLogs(prev => [...prev, { time: new Date().toLocaleTimeString(), event: 'Error', message: data.error }]);
        return;
      }

      if (data.status === 'queued') {
        setStatus('queued');
        setQueuePosition(data.position);
      } else {
        setStatus('running');
      }

      setCurrentJobId(data.job_id);
      connectWebSocket(data.job_id);

    } catch (err) {
      setStatus('error');
      setLogs(prev => [...prev, { time: new Date().toLocaleTimeString(), event: 'Connection Failed', message: String(err) }]);
    }
  };

  const connectWebSocket = (jobId) => {
    if (ws.current) ws.current.close();
    
    ws.current = new WebSocket('ws://localhost:8000/ws');
    
    ws.current.onopen = () => {
      setLogs(prev => [...prev, { time: new Date().toLocaleTimeString(), event: 'WS Connected', message: 'Esperando eventos...' }]);
    };
    
    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.job_id !== jobId) return;

      const time = new Date().toLocaleTimeString();
      let logMsg = '';
      
      if (data.event === 'queue_update') {
        setQueuePosition(data.position);
        logMsg = `Posición en la fila actualizada: #${data.position}`;
      } else if (data.event === 'job_started') {
        setStatus('running');
        logMsg = '¡Es tu turno! Iniciando motor de búsqueda...';
      } else if (data.event === 'zone_start') {
        setStats(s => ({ ...s, current_zone: s.current_zone + 1 }));
        logMsg = `Iniciando tienda: ${data.store?.name || '?'}`;
      } else if (data.event === 'batch_done') {
        setStats(s => ({ ...s, skus_found: s.skus_found + data.found_in_batch }));
        logMsg = `Búsqueda completada. Encontrados: ${data.found_in_batch}`;
      } else if (data.event === 'job_finished') {
        setStatus('finished');
        logMsg = `Trabajo completado. Total resultados: ${data.results_count}`;
        ws.current.close();
      } else if (data.event === 'job_error') {
        setStatus('error');
        logMsg = `Error crítico: ${data.error}`;
        ws.current.close();
      } else {
        logMsg = data.event;
      }

      setLogs(prev => [...prev, { time, event: data.event, message: logMsg, store: data.store?.name }]);
    };
  };

  const progressPct = Math.min(100, Math.round((stats.current_zone / stats.total_zones) * 100));

  return (
    <div>
      <h1 style={{ color: 'var(--text-white)', fontSize: '32px', marginBottom: '8px' }}>Scraper Dashboard</h1>
      <p style={{ marginBottom: '32px' }}>Lanza motores de extracción y monitorea en tiempo real.</p>

      {status === 'idle' && (
        <div className="glass-panel" style={{ padding: '32px', marginBottom: '32px' }}>
          <h2 style={{ color: 'var(--text-white)', marginBottom: '24px' }}>Configuración de Ejecución</h2>
          
          <div style={{ display: 'flex', gap: '24px', marginBottom: '32px' }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: 'block', marginBottom: '8px', color: 'var(--accent)' }}>Motor de Extracción</label>
              <select 
                value={scraperType} 
                onChange={e => setScraperType(e.target.value)}
                style={{ width: '100%', padding: '12px', borderRadius: '8px', background: 'rgba(0,0,0,0.5)', border: '1px solid var(--glass-border)', color: 'white' }}
              >
                <option value="sodimac">Sodimac (MK6)</option>
                <option value="falabella">Falabella (MK7)</option>
                <option value="construmart">Construmart (MK7)</option>
                <option value="maestra_seccion">Maestra Sección (Full Web)</option>
                <option value="precios_mayoristas">Precios Mayoristas (Full Web)</option>
              </select>
            </div>
          </div>

          {(scraperType === 'maestra_seccion' || scraperType === 'precios_mayoristas') ? (
            <div className="upload-area">
              <input 
                type="text" 
                placeholder="https://sodimac.falabella.com/sodimac-cl/category/..." 
                value={categoryUrl}
                onChange={(e) => setCategoryUrl(e.target.value)}
                style={{
                  width: '100%',
                  padding: '16px',
                  borderRadius: '8px',
                  border: '1px solid var(--glass-border)',
                  background: 'rgba(0,0,0,0.5)',
                  color: 'white',
                  fontSize: '16px',
                  marginBottom: '16px'
                }}
              />
              <p style={{ color: 'var(--text-gray)' }}>Pega el enlace de la categoría que deseas extraer.</p>
            </div>
          ) : (
            <div 
              className={`upload-area ${file ? 'active' : ''}`}
              onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files[0]); }}
              onDragOver={(e) => e.preventDefault()}
            >
              <Upload size={32} color="var(--accent)" style={{ marginBottom: '16px' }} />
              <h3 style={{ margin: '0 0 8px 0', color: 'var(--text-white)' }}>
                {file ? file.name : 'Subir Archivo de SKUs'}
              </h3>
              <p style={{ margin: 0, color: 'var(--text-gray)' }}>Formatos soportados: .xlsx, .csv</p>
              
              <input 
                type="file" 
                accept=".csv,.xlsx" 
                onChange={(e) => setFile(e.target.files[0])}
                style={{ opacity: 0, position: 'absolute', inset: 0, width: '100%', cursor: 'pointer' }}
              />
            </div>
          )}

          <div style={{ textAlign: 'right', marginTop: '24px' }}>
            <button 
              className="btn-primary" 
              onClick={startScraping}
              disabled={status === 'running' || status === 'queued'}
            >
              <Play size={20} />
              Iniciar Scraper
            </button>
          </div>
        </div>
      )}

      {status !== 'idle' && (
        <>
          <div className="dashboard-grid">
            <div className="glass-panel stat-card">
              <span className="stat-title">Estado Global</span>
              <span className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '12px', color: status === 'finished' ? '#4CAF50' : status === 'error' ? '#F44336' : status === 'queued' ? '#FFC107' : 'var(--accent)' }}>
                {status === 'running' && <Play size={28} />}
                {status === 'queued' && <span style={{ fontSize: '24px' }}>⏳</span>}
                {status === 'finished' && <CheckCircle size={28} />}
                {status === 'error' && <AlertTriangle size={28} />}
                {status.toUpperCase()}
              </span>
              {status === 'queued' && (
                <div style={{ marginTop: '8px', color: '#FFC107', fontSize: '14px' }}>
                  Servidores ocupados. Estás en la posición <b>#{queuePosition}</b> de la fila.
                </div>
              )}
            </div>
            
            <div className="glass-panel stat-card">
              <span className="stat-title">Zonas Revisadas</span>
              <span className="stat-value">{stats.current_zone} / {stats.total_zones}</span>
              <div className="progress-container">
                <div className="progress-fill" style={{ width: `${progressPct}%` }}></div>
              </div>
            </div>

            <div className="glass-panel stat-card">
              <span className="stat-title">Resultados Encontrados</span>
              <span className="stat-value">{stats.skus_found}</span>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: '24px' }}>
            <h3 style={{ color: 'var(--text-white)', marginBottom: '16px' }}>Terminal de Eventos</h3>
            <div className="terminal-window">
              {logs.map((log, i) => (
                <div key={i} className="log-entry">
                  <span className="log-time">[{log.time}]</span>
                  <span className="log-event">{log.event.padEnd(16)}</span>
                  {log.store && <span className="log-store"> | {log.store.padEnd(20)}</span>}
                  <span style={{ color: '#DDD', marginLeft: '8px' }}>{log.message}</span>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
            
            {status === 'finished' && (
              <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'flex-end', gap: '16px' }}>
                <a 
                  href={`http://localhost:8000/api/download/${currentJobId}`} 
                  className="btn-primary" 
                  style={{ background: '#4CAF50', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}
                  download
                >
                  <Database size={20} />
                  Descargar Excel
                </a>
                <button className="btn-primary" onClick={() => { setStatus('idle'); setFile(null); }}>
                  <CheckCircle size={20} />
                  Nuevo Trabajo
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
