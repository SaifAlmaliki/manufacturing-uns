import React from 'react';
import { ResizableSidebar } from '../ui/resizable-sidebar';
import { UnsTreeView } from './UnsTreeView';
import { PayloadInspector } from './PayloadInspector';
import { LiveMqttFeed } from './LiveMqttFeed';

export const HomeView: React.FC = () => {
  return (
    <div
      id="home-view-container"
      className="flex h-full w-full flex-1 flex-col overflow-y-auto bg-background md:flex-row md:overflow-hidden"
    >
      <ResizableSidebar
        id="section-uns-tree"
        storageKey="uns_console_home_tree_width"
        defaultWidth={320}
        aria-label="UNS Hierarchy Tree"
        className="h-[300px] border-b border-border bg-surface md:h-full md:border-b-0 md:border-r"
      >
        <UnsTreeView />
      </ResizableSidebar>

      <section
        id="section-payload-inspector"
        aria-label="Payload Inspector"
        className="flex min-h-[340px] min-w-0 flex-1 flex-col overflow-hidden border-b border-border bg-surface md:h-full md:border-b-0 md:border-r"
      >
        <PayloadInspector />
      </section>

      <section
        id="section-live-mqtt-feed"
        aria-label="Live MQTT Stream"
        className="h-[300px] min-w-0 flex-1 overflow-hidden bg-surface md:h-full"
      >
        <LiveMqttFeed />
      </section>
    </div>
  );
};

