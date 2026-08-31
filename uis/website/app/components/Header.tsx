import Link from "next/link";

export default function Header() {
  return (
    <header className="sticky top-0 z-[100] flex items-center justify-between gap-4 border-b border-[rgba(16,16,16,0.06)] bg-[rgba(255,250,243,0.82)] px-[5%] py-[18px] backdrop-blur-[14px] md:px-[8%]">
      <Link
        href="/"
        className="font-[family-name:var(--font-space-grotesk)] text-[1.55rem] font-bold tracking-[-0.04em] text-[#101010]"
      >
        Health<span className="text-[#ff6a3d]">Core</span>
      </Link>
      <nav className="flex flex-wrap gap-x-[18px] gap-y-3">
        <Link
          href="/about"
          className="font-semibold text-[#101010] no-underline transition-colors duration-300 hover:text-[#ff6a3d]"
        >
          About
        </Link>
        <Link
          href="/clinics"
          className="font-semibold text-[#101010] no-underline transition-colors duration-300 hover:text-[#ff6a3d]"
        >
          Clinics
        </Link>
        <Link
          href="/careers"
          className="font-semibold text-[#101010] no-underline transition-colors duration-300 hover:text-[#ff6a3d]"
        >
          Careers
        </Link>
      </nav>
    </header>
  );
}