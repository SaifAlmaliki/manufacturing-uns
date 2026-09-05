import React from 'react';
import { UnsTreeView } from './UnsTreeView';
import { PayloadInspector } from './PayloadInspector';
import { LiveMqttFeed } from './LiveMqttFeed';

export const HomeView: React.FC = () => {
  return (
    <div
      id="home-view-container"
      className="flex-1 flex flex-col md:grid md:grid-cols-12 h-full w-full overflow-y-auto md:overflow-hidden bg-background"
    >
      <section
        id="section-uns-tree"
        aria-label="UNS Hierarchy Tree"
        className="h-[300px] md:h-full md:col-span-4 lg:col-span-3 overflow-hidden border-b md:border-b-0 md:border-r border-border shrink-0 bg-surface"
      >
        <UnsTreeView />
      </section>

      <section
        id="section-payload-inspector"
        aria-label="Payload Inspector"
        className="min-h-[340px] md:h-full md:col-span-4 lg:col-span-5 overflow-hidden border-b md:border-b-0 md:border-r border-border flex flex-col bg-surface"
      >
        <PayloadInspector />
      </section>

      <section
        id="section-live-mqtt-feed"
        aria-label="Live MQTT Stream"
        className="h-[300px] md:h-full md:col-span-4 lg:col-span-4 overflow-hidden shrink-0 bg-surface"
      >
        <LiveMqttFeed />
      </section>
    </div>
  );
};

