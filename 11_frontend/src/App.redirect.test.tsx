import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

describe('condition monitoring routes', () => {
  it('redirects /tree to /condition-monitoring', () => {
    render(
      <MemoryRouter initialEntries={['/tree']}>
        <Routes>
          <Route path="/condition-monitoring" element={<div>CM_PAGE</div>} />
          <Route path="/tree" element={<Navigate to="/condition-monitoring" replace />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('CM_PAGE')).toBeTruthy();
  });

  it('wires the same redirect and view in App.tsx', () => {
    const src = readFileSync(resolve(__dirname, './App.tsx'), 'utf8');
    expect(src).toMatch(/path="\/condition-monitoring"/);
    expect(src).toMatch(/ConditionMonitoringView/);
    expect(src).toMatch(/path="\/tree"/);
    expect(src).toMatch(/Navigate to="\/condition-monitoring"/);
  });

  it('renames the sidebar entry', () => {
    const src = readFileSync(resolve(__dirname, './components/layout/Sidebar.tsx'), 'utf8');
    expect(src).toMatch(/Condition Monitoring/);
    expect(src).toMatch(/\/condition-monitoring/);
    expect(src).not.toMatch(/label: 'UNS Tree'/);
  });

  it('uses a title-only header', () => {
    const src = readFileSync(resolve(__dirname, './components/common/Header.tsx'), 'utf8');
    expect(src).toMatch(/condition-monitoring/);
    expect(src).toMatch(/title: 'Condition Monitoring'/);
  });
});

describe('streams route removed', () => {
  it('does not mount Kafka Streams', () => {
    const src = readFileSync(resolve(__dirname, './App.tsx'), 'utf8');
    expect(src).not.toMatch(/KafkaStreamsView/);
    expect(src).toMatch(/path="\/streams" element=\{<Navigate to="\/dashboard"/);
  });

  it('drops Streams from the sidebar', () => {
    const src = readFileSync(resolve(__dirname, './components/layout/Sidebar.tsx'), 'utf8');
    expect(src).not.toMatch(/to: '\/streams'/);
    expect(src).not.toMatch(/label: 'Streams'/);
  });

  it('drops the Kafka Streams page heading', () => {
    const src = readFileSync(resolve(__dirname, './components/common/Header.tsx'), 'utf8');
    expect(src).not.toMatch(/Kafka Streams/);
    expect(src).not.toMatch(/path\.startsWith\('\/streams'\)/);
  });
});

describe('connectivity routes', () => {
  it('splits servers and signals onto their own paths', () => {
    const src = readFileSync(resolve(__dirname, './App.tsx'), 'utf8');
    expect(src).toMatch(/path="\/connectivity"/);
    expect(src).toMatch(/Navigate to="(?:\/connectivity\/)?servers"/);
    expect(src).toMatch(/path="(?:\/connectivity\/)?servers"/);
    expect(src).toMatch(/path="(?:\/connectivity\/)?signals"/);
  });
});
