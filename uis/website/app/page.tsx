import Link from "next/link";

export default function Home() {
  return (
    <>
      <section className="grid min-h-[calc(100vh-90px)] grid-cols-1 items-center gap-12 px-[5%] pb-16 pt-12 md:px-[8%] lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <div>
          <p className="mb-[18px] inline-block text-[0.78rem] font-extrabold uppercase tracking-[0.14em] text-[#ff6a3d]">
            Continuity over convenience
          </p>
          <h1 className="mb-[22px] max-w-[11ch] font-[family-name:var(--font-space-grotesk)] text-[clamp(3rem,6vw,5.6rem)] leading-[0.94] tracking-[-0.06em]">
            Care that follows you, clinic to clinic.
          </h1>
          <p className="mb-[30px] max-w-[610px] text-[1.08rem] text-[#5f5a54]">
            HealthCore connects 12 outpatient clinics across the US and UK
            through a shared digital backbone — so your history is always
            there, wherever you visit.
          </p>
          <div className="flex flex-wrap gap-[14px]">
            <Link
              href="/clinics"
              className="inline-flex min-h-[52px] items-center justify-center rounded-full bg-[#ff6a3d] px-6 py-3 font-extrabold text-white no-underline transition duration-300 hover:-translate-y-0.5 hover:bg-[#e4542c]"
            >
              Find a clinic
            </Link>
            <Link
              href="/about"
              className="inline-flex min-h-[52px] items-center justify-center rounded-full border border-[rgba(16,16,16,0.12)] bg-[rgba(255,255,255,0.64)] px-6 py-3 font-extrabold text-[#101010] no-underline transition duration-300 hover:-translate-y-0.5"
            >
              Our story
            </Link>
          </div>
        </div>

        <div className="grid gap-[18px]">
          <div className="flex min-h-[250px] flex-col justify-end rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-[linear-gradient(135deg,rgba(255,106,61,0.18),rgba(255,255,255,0.95)),#ffffff] p-7 shadow-[0_20px_50px_rgba(16,16,16,0.08)]">
            <p className="mb-[14px] block text-[0.76rem] font-extrabold uppercase tracking-[0.12em] text-[#5f5a54]">
              Clinics connected
            </p>
            <strong className="font-[family-name:var(--font-space-grotesk)] text-[clamp(2rem,4vw,3.4rem)] leading-none tracking-[-0.06em]">
              12
            </strong>
            <span className="mt-3 text-[#5f5a54]">
              Across the US and UK, one shared record system.
            </span>
          </div>

          <div className="grid grid-cols-2 gap-[18px]">
            <div className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-[linear-gradient(180deg,#ffd7cb,#fff3ee)] p-7 shadow-[0_20px_50px_rgba(16,16,16,0.08)]">
              <p className="mb-[14px] block text-[0.76rem] font-extrabold uppercase tracking-[0.12em] text-[#5f5a54]">
                Founded
              </p>
              <strong className="font-[family-name:var(--font-space-grotesk)] text-[clamp(2rem,4vw,3.4rem)] leading-none tracking-[-0.06em]">
                2011
              </strong>
            </div>
            <div className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-[#171717] p-7 text-white shadow-[0_20px_50px_rgba(16,16,16,0.08)]">
              <p className="mb-[14px] block text-[0.76rem] font-extrabold uppercase tracking-[0.12em] text-[rgba(255,255,255,0.7)]">
                Regions
              </p>
              <strong className="font-[family-name:var(--font-space-grotesk)] text-[clamp(2rem,4vw,3.4rem)] leading-none tracking-[-0.06em]">
                2
              </strong>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}