import Link from "next/link";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/stocks", label: "Stocks" },
  { href: "/signals", label: "Signals" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-b border-zinc-200 dark:border-zinc-800">
        {/* Scrolls sideways on narrow screens instead of widening the page. */}
        <nav className="mx-auto flex w-full lg:w-[85%] gap-6 overflow-x-auto whitespace-nowrap px-4 py-3 text-sm">
          <Link href="/dashboard" className="font-semibold">
            VYNZO
          </Link>
          {NAV.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full lg:w-[85%] flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
