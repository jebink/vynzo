// Admin: choose which companies and exchanges the daily pipeline ingests.
import { IngestionSelection } from "@/features/ingestion-selection/ingestion-selection";

export const metadata = { title: "Admin · Daily ingestion" };

export default function AdminPage() {
  return <IngestionSelection />;
}
