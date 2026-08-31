const clinics = [
  { name: "Bristol Central", country: "UK" },
  { name: "London Riverside", country: "UK" },
  { name: "Manchester North", country: "UK" },
  { name: "Edinburgh Old Town", country: "UK" },
  { name: "Cardiff Bay", country: "UK" },
  { name: "Tampa Bay", country: "US" },
  { name: "Orlando Metro", country: "US" },
  { name: "Miami Coastal", country: "US" },
  { name: "Jacksonville East", country: "US" },
  { name: "Austin Central", country: "US" },
  { name: "Charlotte Uptown", country: "US" },
  { name: "Atlanta Midtown", country: "US" },
];

export default function Clinics() {
  return (
    <div className="px-[5%] py-[84px] md:px-[8%]">
      <div className="mb-10 max-w-[760px]">
        <p className="mb-[18px] inline-block text-[0.78rem] font-extrabold uppercase tracking-[0.14em] text-[#ff6a3d]">
          Coverage
        </p>
        <h1 className="font-[family-name:var(--font-space-grotesk)] text-[clamp(2rem,4vw,3.4rem)] leading-none tracking-[-0.05em]">
          12 clinics, one connected network.
        </h1>
        <p className="mt-4 text-[#5f5a54]">
          Every clinic shares the same digital backbone, so your care history
          travels with you across the US and UK.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-3">
        {clinics.map((clinic) => (
          <div
            key={clinic.name}
            className="rounded-[28px] border border-[rgba(16,16,16,0.06)] bg-[rgba(255,255,255,0.85)] p-7 shadow-[0_14px_30px_rgba(16,16,16,0.05)] transition duration-300 hover:-translate-y-1.5 hover:shadow-[0_22px_40px_rgba(16,16,16,0.1)]"
          >
            <p className="font-[family-name:var(--font-space-grotesk)] text-[1.2rem]">
              {clinic.name}
            </p>
            <p className="mt-2 text-[0.85rem] font-extrabold uppercase tracking-[0.12em] text-[#ff6a3d]">
              {clinic.country}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}