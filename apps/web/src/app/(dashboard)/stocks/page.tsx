// Directory of every ingested stock. Detail pages live under ./[symbol].
import { StockDirectory } from "@/features/stock-directory/stock-directory";

export const metadata = { title: "Stocks" };

export default function StocksDirectoryPage() {
  return <StockDirectory />;
}
