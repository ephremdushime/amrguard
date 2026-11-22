import React, { useState } from 'react';
import { CheckCircle2, FileSearch, Filter, Layers, Search } from 'lucide-react';
import type { OperationalRx } from '../types';

interface PrescriptionQueueProps {
  prescriptions: OperationalRx[];
  selectedRx: OperationalRx | null;
  onSelect: (rx: OperationalRx) => void;
  title?: string;
  eyebrow?: string;
}

export function PrescriptionQueue({
  prescriptions,
  selectedRx,
  onSelect,
  title = 'Prescription register',
  eyebrow = 'INCOMING PRESCRIPTIONS',
}: PrescriptionQueueProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const filtered = prescriptions.filter((rx) => {
    const matchesSearch =
      rx.code.toLowerCase().includes(searchTerm.toLowerCase()) ||
      rx.patient_reference.toLowerCase().includes(searchTerm.toLowerCase()) ||
      rx.external_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      rx.items.some(
        (i) =>
          i.antibiotic.toLowerCase().includes(searchTerm.toLowerCase()) ||
          i.code.toLowerCase().includes(searchTerm.toLowerCase()),
      );

    if (!matchesSearch) return false;
    if (statusFilter === 'ALL') return true;
    return rx.status === statusFilter;
  });

  return (
    <section className="panel operationsQueue">
      <div className="panelHead">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>
            {title} ({filtered.length})
          </h2>
        </div>
        <FileSearch size={19} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, margin: '8px 0 12px' }}>
        <div style={{ position: 'relative' }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: 11, color: 'var(--muted)' }} />
          <input
            type="text"
            placeholder="Search code, patient, external ID…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ paddingLeft: 30, fontSize: '13px' }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <Filter size={14} style={{ color: 'var(--muted)' }} />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ fontSize: '13px', padding: '6px 8px' }}
          >
            <option value="ALL">All statuses</option>
            <option value="VALIDATED">Validated</option>
            <option value="ACTIVE">Active (Cred Issued)</option>
            <option value="PARTIALLY_DISPENSED">Partially Dispensed</option>
            <option value="COMPLETED">Completed</option>
            <option value="WARNING">Warning</option>
            <option value="BLOCKED">Blocked</option>
          </select>
        </div>
      </div>

      <div className="queueList" style={{ maxHeight: 520, overflowY: 'auto' }}>
        {filtered.length ? (
          filtered.map((order) => {
            const isSelected = selectedRx?.id === order.id;
            const totalItems = order.items.length;
            const primaryItem = order.items[0];

            return (
              <button
                type="button"
                className={`queueRow ${isSelected ? 'selected' : ''}`}
                key={order.id}
                onClick={() => onSelect(order)}
                style={{ textAlign: 'left', width: '100%' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className={`queueStatus status-${order.status.toLowerCase()}`}>{order.status}</span>
                  {totalItems > 1 && (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                        fontSize: '11px',
                        fontWeight: 600,
                        background: 'var(--bg-subtle, #f1f5f9)',
                        padding: '2px 6px',
                        borderRadius: 4,
                      }}
                    >
                      <Layers size={11} /> {totalItems} items
                    </span>
                  )}
                </div>

                <strong>{order.code}</strong>

                {primaryItem && (
                  <span>
                    {primaryItem.antibiotic} {primaryItem.strength} · {primaryItem.authorized_quantity} units
                  </span>
                )}

                <small>
                  {order.patient_reference} · {order.facility.name} · Source {order.external_id}
                </small>
              </button>
            );
          })
        ) : (
          <div className="emptyState">
            <span>
              <CheckCircle2 size={24} />
            </span>
            <strong>No prescriptions match filter</strong>
            <p>Adjust your search criteria or select another status to view queued orders.</p>
          </div>
        )}
      </div>
    </section>
  );
}
