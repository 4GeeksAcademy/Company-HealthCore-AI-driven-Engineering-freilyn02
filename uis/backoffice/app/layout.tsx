import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HealthCore Backoffice",
  description: "Internal tools for HealthCore Digital staff",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50">
        <header className="bg-blue-800 text-white px-6 py-4">
          <h1 className="font-bold text-lg">HealthCore Backoffice</h1>
        </header>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}