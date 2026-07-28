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
      <div className="px-6 py-16 max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-blue-700 mb-6">Our clinics</h1>
        <p className="text-gray-600 mb-10">
          12 clinics across the US and UK, connected by a shared digital
          backbone.
        </p>
  
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {clinics.map((clinic) => (
            <div
              key={clinic.name}
              className="border border-gray-200 rounded-md p-4"
            >
              <p className="font-medium">{clinic.name}</p>
              <p className="text-sm text-gray-500">{clinic.country}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }