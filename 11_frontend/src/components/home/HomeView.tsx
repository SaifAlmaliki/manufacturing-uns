import React from 'react';
import { UnsTreeView } from './UnsTreeView';
import { PayloadInspector } from './PayloadInspector';
import { LiveMqttFeed } from './LiveMqttFeed';

export const HomeView: React.FC = () => {
  return (
    <div
      id="home-view-container"
      className="flex-1 flex flex-col md:grid md:grid-cols-12 h-full w-full overflow-y-auto md:overflow-hidden bg-[#F8FAFC] dark:bg-[#0B0B0C]"
    >
      {/* Pane 1: ISA-95 UNS Tree Browser */}
      <section
        id="section-uns-tree"
        aria-label="UNS Hierarchy Tree"
        className="h-[300px] md:h-full md:col-span-4 lg:col-span-3 overflow-hidden border-b md:border-b-0 md:border-r border-[#E2E8F0] dark:border-[#1E293B] shrink-0"
      >
        <UnsTreeView />
      </section>

      {/* Pane 2: Selected Node Payload Inspector */}
      <section
        id="section-payload-inspector"
        aria-label="Payload Inspector"
        className="min-h-[340px] md:h-full md:col-span-4 lg:col-span-5 overflow-hidden border-b md:border-b-0 md:border-r border-[#E2E8F0] dark:border-[#1E293B] flex flex-col"
      >
        <PayloadInspector />
      </section>

      {/* Pane 3: Live MQTT Stream Feed */}
      <section
        id="section-live-mqtt-feed"
        aria-label="Live MQTT Stream"
        className="h-[300px] md:h-full md:col-span-4 lg:col-span-4 overflow-hidden shrink-0"
      >
        <LiveMqttFeed />
      </section>
    </div>
  );
};

