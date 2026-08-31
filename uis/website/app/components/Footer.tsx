export default function Footer() {
  return (
    <footer className="border-t border-[rgba(16,16,16,0.06)] px-5 py-7 text-center text-[0.9rem] text-[#5f5a54]">
      <p>&copy; {new Date().getFullYear()} HealthCore Digital. Outpatient care across the US and UK.</p>
    </footer>
  );
}