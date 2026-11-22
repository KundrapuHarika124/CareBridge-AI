
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import "leaflet/dist/leaflet.css";

import {
  del,
  get,
  patch,
  post,
  query,
  type Hospital,
} from "../api";

import {
  Banner,
  Button,
  Card,
  ErrorPanel,
  Field,
  Loading,
  PageTitle,
  useAction,
  useLoad,
} from "../ui";

interface PlatformStats {
  total_hospitals: number;
  approved_hospitals: number;
  pending_hospitals: number;
  total_users: number;
  super_admins: number;
  hospital_admins: number;
  doctors: number;
  patients: number;
  caregivers: number;
}

interface LocationResult {
  display_name: string;
  latitude: number;
  longitude: number;
}

interface SelectedLocation {
  latitude: number;
  longitude: number;
}

export default function SuperAdmin() {
  const { t } = useTranslation();

  const data = useLoad(async () => {
    const [stats, hospitals] = await Promise.all([
      get<PlatformStats>("/admin/stats"),
      get<Hospital[]>("/admin/hospitals?include_unapproved=true"),
    ]);

    return { stats, hospitals };
  }, []);

  const action = useAction();

  const [notice, setNotice] = useState("");

  const [form, setForm] = useState({
    name: "",
    locality: "",
    city: "Hyderabad",
    address: "",
    phone: "",
    latitude: "",
    longitude: "",
    admin_name: "",
    admin_email: "",
    admin_password: "",
  });

  // Location picker state
  const [locationResults, setLocationResults] = useState<LocationResult[]>([]);
  const [selectedLocation, setSelectedLocation] =
    useState<SelectedLocation | null>(null);
  const [locationSearching, setLocationSearching] = useState(false);
  const [locationError, setLocationError] = useState("");

  // Leaflet map references
  const mapElementRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<import("leaflet").Map | null>(null);
  const markerRef = useRef<import("leaflet").Marker | null>(null);

  const set = (key: keyof typeof form) =>
    (event: { target: { value: string } }) => {
      setForm((previous) => ({
        ...previous,
        [key]: event.target.value,
      }));
    };

  // Search for a hospital address using the backend.
  const searchLocation = async () => {
    const searchText = form.address.trim();

    if (searchText.length < 3) {
      setLocationError("Enter at least 3 characters in the address field.");
      return;
    }

    setLocationSearching(true);
    setLocationError("");
    setLocationResults([]);

    try {
      const results = await get<LocationResult[]>(
        `/admin/location-search${query({ q: searchText })}`
      );

      setLocationResults(results);

      if (results.length === 0) {
        setLocationError("No matching locations found. Try another address.");
      }
    } catch (error) {
      setLocationError(
        error instanceof Error
          ? error.message
          : "Location search failed. Please try again."
      );
    } finally {
      setLocationSearching(false);
    }
  };

  // Select a search result and automatically populate coordinates.
  const selectLocation = (result: LocationResult) => {
    setSelectedLocation({
      latitude: result.latitude,
      longitude: result.longitude,
    });

    setForm((previous) => ({
      ...previous,
      address: result.display_name.slice(0, 300),
      latitude: String(result.latitude),
      longitude: String(result.longitude),
    }));

    setLocationResults([]);
    setLocationError("");
  };

  // Initialize and update the interactive Leaflet map.
  useEffect(() => {
    let cancelled = false;

    if (!selectedLocation) {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        markerRef.current = null;
      }

      return;
    }

    const initializeMap = async () => {
      const L = await import("leaflet");

      if (cancelled || !mapElementRef.current) return;

      const position: [number, number] = [
        selectedLocation.latitude,
        selectedLocation.longitude,
      ];

      if (!mapRef.current) {
        const map = L.map(mapElementRef.current).setView(position, 15);

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          maxZoom: 19,
        }).addTo(map);

        const marker = L.marker(position, {
          draggable: true,
        }).addTo(map);

        marker.bindPopup("Drag this marker to adjust the hospital location.");

        marker.on("dragend", () => {
          const coordinates = marker.getLatLng();

          setSelectedLocation({
            latitude: coordinates.lat,
            longitude: coordinates.lng,
          });

          setForm((previous) => ({
            ...previous,
            latitude: String(coordinates.lat),
            longitude: String(coordinates.lng),
          }));
        });

        mapRef.current = map;
        markerRef.current = marker;

        map.whenReady(() => map.invalidateSize());
      } else {
        mapRef.current.setView(position, 15);
        markerRef.current?.setLatLng(position);
        mapRef.current.invalidateSize();
      }
    };

    void initializeMap();

    return () => {
      cancelled = true;
    };
  }, [selectedLocation]);

  // Clean up Leaflet when the page is unmounted.
  useEffect(() => {
    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
  }, []);

  if (data.loading) return <Loading />;

  if (data.error) {
    return <ErrorPanel error={data.error} onRetry={data.reload} />;
  }

  if (!data.data) return null;

  // Create hospital.
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setNotice("");

    const created = await action.run(() =>
      post<{ hospital: Hospital; admin_email: string }>(
        "/admin/hospitals",
        {
          name: form.name.trim(),
          locality: form.locality.trim(),
          city: form.city.trim(),
          address: form.address.trim(),
          phone: form.phone.trim(),
          latitude: form.latitude ? Number(form.latitude) : null,
          longitude: form.longitude ? Number(form.longitude) : null,
          admin_name: form.admin_name.trim(),
          admin_email: form.admin_email.trim() || null,
          admin_password: form.admin_password,
        }
      )
    );

    if (created) {
      setNotice(
        t("superAdmin.hospitalCreated", {
          email: created.admin_email,
        })
      );

      setForm({
        name: "",
        locality: "",
        city: "Hyderabad",
        address: "",
        phone: "",
        latitude: "",
        longitude: "",
        admin_name: "",
        admin_email: "",
        admin_password: "",
      });

      setSelectedLocation(null);
      setLocationResults([]);
      setLocationError("");

      data.reload();
    }
  };

  // Approve or reject hospital.
  const changeApproval = async (
    hospital: Hospital,
    isApproved: boolean
  ) => {
    setNotice("");

    const changed = await action.run(() =>
      patch<Hospital>(`/admin/hospitals/${hospital.id}`, {
        is_approved: isApproved,
      })
    );

    if (changed) {
      setNotice(
        isApproved
          ? t("superAdmin.approved")
          : t("superAdmin.rejected")
      );

      data.reload();
    }
  };

  // Delete hospital.
  const removeHospital = async (hospital: Hospital) => {
    if (
      !window.confirm(
        t("superAdmin.confirmDelete", { name: hospital.name })
      )
    ) {
      return;
    }

    setNotice("");

    if (
      await action.run(() =>
        del(`/admin/hospitals/${hospital.id}`)
      )
    ) {
      setNotice(t("superAdmin.deleted"));
      data.reload();
    }
  };

  const { stats, hospitals } = data.data;

  const tiles: [string, number][] = [
    [t("superAdmin.totalHospitals"), stats.total_hospitals],
    [t("superAdmin.approvedHospitals"), stats.approved_hospitals],
    [t("superAdmin.pendingHospitals"), stats.pending_hospitals],
    [t("superAdmin.totalUsers"), stats.total_users],
  ];

  return (
    <div>
      <PageTitle>{String(t("superAdmin.title"))}</PageTitle>

      {action.error != null && (
        <ErrorPanel error={action.error} />
      )}

      {notice && (
        <Banner kind="success">{notice}</Banner>
      )}

      {/* Platform statistics */}
      <dl className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={String(label)} className="card">
            <dt className="text-slate-700">{label}</dt>
            <dd className="text-3xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      {/* Hospital registration */}
      <Card className="mb-6">
        <h2 className="mb-3 font-semibold">
          {t("superAdmin.createHospital")}
        </h2>

        <form
          onSubmit={submit}
          className="grid gap-x-4 sm:grid-cols-2"
        >
          <Field label={t("superAdmin.hospitalName")}>
            {(id) => (
              <input
                id={id}
                className="input"
                value={form.name}
                onChange={set("name")}
                required
                minLength={2}
              />
            )}
          </Field>

          <Field label={t("superAdmin.locality")}>
            {(id) => (
              <input
                id={id}
                className="input"
                value={form.locality}
                onChange={set("locality")}
                required
              />
            )}
          </Field>

          <Field label={t("superAdmin.city")}>
            {(id) => (
              <input
                id={id}
                className="input"
                value={form.city}
                onChange={set("city")}
                required
              />
            )}
          </Field>

          <Field label={t("superAdmin.phone")}>
            {(id) => (
              <input
                id={id}
                className="input"
                value={form.phone}
                onChange={set("phone")}
              />
            )}
          </Field>

          {/* Address search */}
          <div className="sm:col-span-2">
            <Field label={t("superAdmin.address")}>
              {(id) => (
                <input
                  id={id}
                  className="input"
                  value={form.address}
                  onChange={(e) => {
                    setForm((prev) => ({
                      ...prev,
                      address: e.target.value,
                      latitude: "",
                      longitude: "",
                    }));
                    setSelectedLocation(null);
                    setLocationResults([]);
                    setLocationError("");
                  }}
                  placeholder="Enter hospital address or area"
                />
              )}
            </Field>

            <button
              type="button"
              onClick={searchLocation}
              disabled={locationSearching}
              className="mt-2 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {locationSearching
                ? "Searching..."
                : "Search location"}
            </button>

            {locationError && (
              <p className="mt-2 text-sm text-red-600">
                {locationError}
              </p>
            )}

            {/* Search results */}
            {locationResults.length > 0 && (
              <div className="mt-3 space-y-2 rounded-lg border p-3">
                <p className="font-medium">
                  Select the correct hospital location:
                </p>

                {locationResults.map((result, index) => (
                  <button
                    key={`${result.latitude}-${result.longitude}-${index}`}
                    type="button"
                    onClick={() => selectLocation(result)}
                    className="block w-full rounded-lg border p-3 text-left text-sm hover:bg-slate-50"
                  >
                    <span className="font-medium">
                      Location {index + 1}
                    </span>
                    <span className="mt-1 block text-slate-600">
                      {result.display_name}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Interactive map */}
          {selectedLocation && (
            <div className="mt-4 sm:col-span-2">
              <h3 className="mb-2 font-medium">
                Adjust hospital location
              </h3>

              <p className="mb-3 text-sm text-slate-600">
                Drag the marker to the exact hospital entrance or
                building location.
              </p>

              <div
                ref={mapElementRef}
                className="h-72 w-full overflow-hidden rounded-lg border"
              />

              <p className="mt-2 text-sm text-green-700">
                <strong>Location selected!</strong> Coordinates are
                automatically saved.
              </p>

              <p className="text-xs text-slate-500">
                Latitude: {Number(form.latitude).toFixed(6)}
                {" | "}
                Longitude: {Number(form.longitude).toFixed(6)}
              </p>

              <p className="mt-1 text-xs text-slate-500">
                Map data © OpenStreetMap contributors.
              </p>
            </div>
          )}

          {/* Hospital administrator details */}
          <Field label={t("superAdmin.adminName")}>
            {(id) => (
              <input
                id={id}
                className="input"
                value={form.admin_name}
                onChange={set("admin_name")}
                required
                minLength={2}
              />
            )}
          </Field>

          <Field label={t("superAdmin.adminEmail")}>
            {(id) => (
              <input
                id={id}
                type="email"
                className="input"
                value={form.admin_email}
                onChange={set("admin_email")}
              />
            )}
          </Field>

          <Field label={t("superAdmin.adminPassword")}>
            {(id) => (
              <input
                id={id}
                type="password"
                className="input"
                value={form.admin_password}
                onChange={set("admin_password")}
                required
                minLength={8}
              />
            )}
          </Field>

          <div className="sm:col-span-2">
            <Button
              type="submit"
              disabled={action.busy}
            >
              {action.busy
                ? t("common.pleaseWait")
                : t("superAdmin.create")}
            </Button>
          </div>
        </form>
      </Card>

      {/* Hospital management */}
      <section>
        <h2 className="mb-3 font-semibold">
          {t("superAdmin.hospitals")}
        </h2>

        {hospitals.length === 0 && (
          <p>{t("superAdmin.noHospitals")}</p>
        )}

        <div className="space-y-3">
          {hospitals.map((hospital) => (
            <Card key={hospital.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-lg font-semibold">
                    {hospital.name}
                  </p>

                  <p className="text-slate-600">
                    {hospital.locality}, {hospital.city}
                  </p>

                  <p className="text-sm text-slate-600">
                    {hospital.is_approved
                      ? t("superAdmin.approvedStatus")
                      : t("superAdmin.pendingStatus")}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  {hospital.is_approved ? (
                    <Button
                      variant="secondary"
                      disabled={action.busy}
                      onClick={() =>
                        changeApproval(hospital, false)
                      }
                    >
                      {t("superAdmin.reject")}
                    </Button>
                  ) : (
                    <Button
                      disabled={action.busy}
                      onClick={() =>
                        changeApproval(hospital, true)
                      }
                    >
                      {t("superAdmin.approve")}
                    </Button>
                  )}

                  <Button
                    variant="danger"
                    disabled={action.busy}
                    onClick={() => removeHospital(hospital)}
                  >
                    {t("superAdmin.delete")}
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
