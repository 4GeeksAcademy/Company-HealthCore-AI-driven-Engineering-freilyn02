import Link from "next/link";

export default function Header() {
  return (
    <header className="border-b border-gray-200 py-4 px-6 flex items-center justify-between">
      <Link href="/" className="text-xl font-bold text-blue-700">
        HealthCore
      </Link>
      <nav className="flex gap-6 text-sm font-medium">
        <Link href="/about">About</Link>
        <Link href="/clinics">Clinics</Link>
        <Link href="/careers">Careers</Link>
      </nav>
    </header>
  );
}