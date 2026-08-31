"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";

interface Profile {
  id: number;
  user_id: number;
  name: string | null;
  phone: string | null;
  address: string | null;
}

interface Me {
  id: number;
  email: string;
  is_active: boolean;
  role: string;
  created_at: string;
  profile: Profile;
}

export default function ProfilePage() {
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    async function loadMe() {
      try {
        const data = await apiFetch<Me>("/auth/me");
        setMe(data);
        setName(data.profile.name ?? "");
        setPhone(data.profile.phone ?? "");
        setAddress(data.profile.address ?? "");
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load profile");
      } finally {
        setLoading(false);
      }
    }
    loadMe();
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaveMessage(null);

    try {
      const updated = await apiFetch<Profile>("/profiles/me", {
        method: "PUT",
        body: JSON.stringify({ name, phone, address }),
      });
      setMe((prev) => (prev ? { ...prev, profile: updated } : prev));
      setSaveMessage("Profile updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="p-6">Loading...</p>;
  if (error && !me) return <p className="p-6 text-red-600">{error}</p>;

  return (
    <div className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">My Profile</h1>

      <p className="mb-4 text-sm text-gray-600">{me?.email}</p>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label htmlFor="name" className="block text-sm font-medium">
            Name
          </label>
          <input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>

        <div>
          <label htmlFor="phone" className="block text-sm font-medium">
            Phone
          </label>
          <input
            id="phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>

        <div>
          <label htmlFor="address" className="block text-sm font-medium">
            Address
          </label>
          <input
            id="address"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {saveMessage && <p className="text-sm text-green-600">{saveMessage}</p>}

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded bg-black px-4 py-2 text-white disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </form>
    </div>
  );
}