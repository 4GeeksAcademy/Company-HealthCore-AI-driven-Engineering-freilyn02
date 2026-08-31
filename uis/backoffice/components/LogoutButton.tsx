"use client";

import { useRouter } from "next/navigation";
import { clearToken } from "@/lib/auth";

export default function LogoutButton() {
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  return (
    <button
      onClick={handleLogout}
      className="rounded px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
    >
      Log out
    </button>
  );
}