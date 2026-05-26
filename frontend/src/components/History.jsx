import React, { useState, useEffect } from 'react';
import { Search, Package, Store } from 'lucide-react';

export default function History() {
  const [data, setData] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://localhost:8000/api/history')
      .then(res => res.json())
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  }, []);

  const filteredData = data.filter(item => 
    (item.sku && item.sku.toLowerCase().includes(search.toLowerCase())) ||
    (item.description && item.description.toLowerCase().includes(search.toLowerCase())) ||
    (item.store_name && item.store_name.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="glass-panel" style={{ padding: '32px', display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h2 style={{ color: 'var(--text-white)', margin: 0 }}>Historial de Precios</h2>
        
        <div style={{ position: 'relative', width: '300px' }}>
          <Search size={18} style={{ position: 'absolute', left: '12px', top: '10px', color: '#888' }} />
          <input 
            type="text" 
            placeholder="Buscar por SKU, nombre o tienda..." 
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 10px 10px 38px',
              borderRadius: '8px',
              border: '1px solid var(--glass-border)',
              background: 'rgba(0,0,0,0.4)',
              color: 'white'
            }}
          />
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px', color: '#888' }}>Cargando datos desde PostgreSQL...</div>
      ) : (
        <div style={{ overflowX: 'auto', flex: 1 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', color: '#DDD' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--glass-border)', textAlign: 'left' }}>
                <th style={{ padding: '12px' }}>Fecha</th>
                <th style={{ padding: '12px' }}>Motor</th>
                <th style={{ padding: '12px' }}>SKU</th>
                <th style={{ padding: '12px' }}>Tienda</th>
                <th style={{ padding: '12px' }}>Descripción</th>
                <th style={{ padding: '12px' }}>Precio</th>
                <th style={{ padding: '12px' }}>Desc.</th>
              </tr>
            </thead>
            <tbody>
              {filteredData.length === 0 ? (
                <tr>
                  <td colSpan="7" style={{ textAlign: 'center', padding: '32px', color: '#888' }}>No hay resultados</td>
                </tr>
              ) : filteredData.map((row, i) => (
                <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '12px', color: '#888', fontSize: '14px' }}>{new Date(row.scraped_at).toLocaleDateString()}</td>
                  <td style={{ padding: '12px' }}>
                    <span style={{ background: 'rgba(255,255,255,0.1)', padding: '4px 8px', borderRadius: '4px', fontSize: '12px' }}>
                      {row.scraper_type}
                    </span>
                  </td>
                  <td style={{ padding: '12px', fontWeight: 'bold', color: 'var(--accent)' }}>{row.sku}</td>
                  <td style={{ padding: '12px' }}>{row.store_name}</td>
                  <td style={{ padding: '12px', maxWidth: '250px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {row.description}
                  </td>
                  <td style={{ padding: '12px', color: '#4CAF50', fontWeight: 'bold' }}>
                    ${(row.price_internet || row.price_normal || row.price_cmr || 0).toLocaleString('es-CL')}
                  </td>
                  <td style={{ padding: '12px' }}>{row.discount_pct || '0'}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
