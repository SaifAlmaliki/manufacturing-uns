export type JobCard = { id: string; prompt: string };

export function jobCards(hasFocus: boolean): JobCard[] {
  if (hasFocus) {
    return [
      {
        id: 'pump-performance',
        prompt: 'Has Pump P101 lost performance over the last three weeks?',
      },
      {
        id: 'alarms-on-asset',
        prompt: 'What is in alarm on the Asset I am looking at?',
      },
      {
        id: 'metric-vs-eight-hours',
        prompt: 'How does this metric compare to the last eight hours?',
      },
      {
        id: 'recent-publishers',
        prompt: 'Which Assets on this path published in the last hour?',
      },
    ];
  }
  return [
    {
      id: 'pump-performance',
      prompt: 'Has Pump P101 lost performance over the last three weeks?',
    },
    {
      id: 'alarms-on-asset',
      prompt: 'What is in alarm in my plant right now?',
    },
    {
      id: 'metric-vs-eight-hours',
      prompt: "How does the selected metric (or this line's main metrics) compare to the last eight hours?",
    },
    {
      id: 'recent-publishers',
      prompt: 'Which Assets on my plant path published in the last hour?',
    },
  ];
}

export const JOB_CARDS: JobCard[] = jobCards(false);
