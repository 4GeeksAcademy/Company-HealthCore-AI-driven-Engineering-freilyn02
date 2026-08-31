export default function About() {
  return (
    <div className="px-[5%] py-[84px] md:px-[8%]">
      <div className="mb-10 max-w-[760px]">
        <p className="mb-[18px] inline-block text-[0.78rem] font-extrabold uppercase tracking-[0.14em] text-[#ff6a3d]">
          Our story
        </p>
        <h1 className="font-[family-name:var(--font-space-grotesk)] text-[clamp(2rem,4vw,3.4rem)] leading-none tracking-[-0.05em]">
          Continuity over convenience.
        </h1>
      </div>

      <div className="grid max-w-[760px] gap-5 text-[#5f5a54]">
        <p>
          HealthCore was founded in 2011 by Dr. Elena Marsh, a former NHS
          general practitioner, and Raj Whitfield, a healthcare operations
          consultant. They identified a shared problem on both sides of the
          Atlantic: patients in mid-sized towns had to travel long distances
          or wait weeks for routine specialist care.
        </p>
        <p>
          Starting with a single clinic in Bristol, UK, and a sister clinic
          in Tampa, Florida, HealthCore grew through a &quot;hub-and-spoke&quot;
          model — small, fully-staffed outpatient clinics connected by a
          shared digital backbone, rather than large centralized hospitals.
        </p>
        <p>
          Today HealthCore operates 12 outpatient clinics across the US and
          UK. Our core bet is continuity over convenience: instead of
          competing on same-day urgent care, we build long-term
          patient-provider relationships by keeping patient records,
          referrals, and follow-ups tightly connected across every clinic in
          the network.
        </p>
      </div>
    </div>
  );
}