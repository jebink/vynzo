import { NeedToFocus } from "@/features/need-to-focus/need-to-focus";
import { NewsRadar } from "@/features/news-radar/news-radar";
import { UpcomingEvents } from "@/features/upcoming-events/upcoming-events";

export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <NeedToFocus />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <NewsRadar />
        <UpcomingEvents />
      </div>
    </div>
  );
}
