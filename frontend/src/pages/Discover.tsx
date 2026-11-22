// Nearby hospital and doctor discovery with real geolocation.
// Uses browser geolocation or manual location search.
// Shows hospitals and doctors on a map (Leaflet) and as cards.

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import "leaflet/dist/leaflet.css";
import { get, query, type DoctorCard, type Hospital } from "../api";
import { can, useAuth } from "../auth";
import { fmtDateTime } from "../lib/format";
import {
  Banner, Button, Card, Empty, ErrorPanel, Loading, PageTitle, SimTag, useLang, useLoad,
} from "../ui";

interface Coordinates { latitude: number; longitude: number }

type Tab = "hospitals" | "doctors";
type DiscoveryStep = "location" | "results" | "doctorResults";

export default function Discover() {
  const { t } = useTranslation();
  const lang = useLang();
  const { activePatient } = useAuth();
  const [step, setStep] = useState<DiscoveryStep>("location");
  const [tab, setTab] = useState<Tab>("hospitals");
  const [coords, setCoords] = useState<Coordinates | null>(null);
  const [locationText, setLocationText] = useState("");
  const [selectedHospital, setSelectedHospital] = useState<Hospital | null>(null);
  const [specialtyId, setSpecialtyId] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInitRef = useRef(false);
  const navigate = useNavigate();

  const canBook = can(activePatient, "BOOK_APPOINTMENTS");

  // Hospitals search
  const hospitals = useLoad(async () => {
    if (!coords) return [];
    const resp = await get<{ data: Hospital[]; total: number }>(
      `/hospitals/nearby${query({ latitude: coords.latitude, longitude: coords.longitude })}`
    );
    return resp.data;
  }, [coords]);

  // Doctors search (when hospital selected)
  const doctors = useLoad(async () => {
    if (!coords || !selectedHospital) return [];
    const resp = await get<{ data: DoctorCard[]; total: number }>(
      `/doctors/nearby${query({
        latitude: coords.latitude,
        longitude: coords.longitude,
        specialty_id: specialtyId,
        locality: selectedHospital.locality,
      })}`
    );
    return resp.data;
  }, [coords, selectedHospital?.id, specialtyId]);

  // Specialties for filtering
  const specialties = useLoad(() => get<{ id: string; code: string; name_en: string; name_te: string }[]>("/specialties"), []);

  const detectLocation = async () => {
    if (!navigator.geolocation) {
      return { error: "Geolocation not supported" };
    }
    return new Promise<{ coords?: Coordinates; error?: string }>((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({
          coords: { latitude: pos.coords.latitude, longitude: pos.coords.longitude }
        }),
        (err) => {
          let msg = t("discover.locationError");
          if (err.code === 1) msg = t("discover.permissionDenied");
          else if (err.code === 2) msg = t("discover.positionUnavailable");
          else if (err.code === 3) msg = t("discover.timeout");
          resolve({ error: msg });
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    });
  };

  const handleDetect = async () => {
    setSearching(true);
    const result = await detectLocation();
    setSearching(false);
    if (result.error) {
      alert(result.error);
      return;
    }
    if (result.coords) {
      setCoords(result.coords);
      setStep("results");
    }
  };

  const handleManualSearch = async () => {
    if (!locationText.trim()) return;
    setSearching(true);
    try {
      // Use Nominatim for geocoding
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(locationText.trim())}&limit=1`,
        { headers: { "User-Agent": "CareBridgeAI/1.0" } }
      );
      const data = await resp.json();
      if (data.length > 0) {
        setCoords({ latitude: parseFloat(data[0].lat), longitude: parseFloat(data[0].lon) });
        setStep("results");
      } else {
        alert(t("discover.locationNotFound"));
      }
    } catch {
      alert(t("discover.geocodingFailed"));
    } finally {
      setSearching(false);
    }
  };

  const pickHospital = (hospital: Hospital) => {
    setSelectedHospital(hospital);
    setTab("doctors");
  };

  const backToHospitals = () => {
    setSelectedHospital(null);
    setTab("hospitals");
  };

  // Initialize Leaflet map
  useEffect(() => {
    if (step !== "results" || !coords || mapInitRef.current) return;
    import("leaflet").then((L) => {
      if (!mapRef.current) return;
      const map = L.map(mapRef.current).setView([coords.latitude, coords.longitude], 12);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);

      // Patient marker
      L.marker([coords.latitude, coords.longitude], {
        icon: L.divIcon({
          className: "patient-marker",
          html: '<div style="width:24px;height:24px;border-radius:50%;background:#2563eb;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3)"></div>',
          iconSize: [24, 24],
        }),
      }).addTo(map).bindPopup(t("discover.yourLocation"));

      // Hospital markers
      (hospitals.data ?? []).forEach((h) => {
        if (h.latitude != null && h.longitude != null) {
          const color = h.is_simulated ? "#f59e0b" : "#10b981";
          L.marker([h.latitude, h.longitude], {
            icon: L.divIcon({
              className: "hospital-marker",
              html: `<div style="width:32px;height:32px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center;color:white;font-weight:bold;font-size:14px">H</div>`,
              iconSize: [32, 32],
            }),
          }).addTo(map).bindPopup(`
            <strong>${h.name}</strong><br>
            ${h.locality}, ${h.city}<br>
            <span style="color:#6b7280;font-size:12px">${h.distance_km?.toFixed(1)} km</span>
            ${h.is_simulated ? '<br><span style="color:#f59e0b;font-size:12px">🔸 Simulated</span>' : ''}
          `);
        }
      });
      mapInitRef.current = true;
    }).catch(() => {
      // Leaflet failed to load
    });
  }, [step, coords, hospitals.data]);

  if (!activePatient) {
    return <Empty title={t("care.choosePatientFirst")} />;
  }

  return (
    <div>
      <PageTitle>{t("discover.title")}</PageTitle>
      <p className="mb-4 text-slate-600">{t("discover.subtitle")}</p>

      {step === "location" && (
        <Card>
          <h2 className="mb-4">{t("discover.findLocation")}</h2>

          <div className="mb-4">
            <Button
              onClick={handleDetect}
              disabled={searching}
              className="w-full sm:w-auto mb-3"
            >
              {searching ? t("common.pleaseWait") : t("discover.useCurrentLocation")}
            </Button>
            <p className="text-sm text-slate-600 mb-3">{t("discover.or")}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <input
              type="text"
              className="input flex-1 min-w-[200px]"
              placeholder={t("discover.enterLocation")}
              value={locationText}
              onChange={(e) => setLocationText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleManualSearch()}
            />
            <Button onClick={handleManualSearch} disabled={searching || !locationText.trim()}>
              {t("discover.search")}
            </Button>
          </div>

          <p className="mt-4 text-sm text-slate-500">
            {t("discover.locationHelp")}
          </p>
        </Card>
      )}

      {step === "results" && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span className="text-sm text-slate-600">{t("discover.showingResults")}</span>
            <div className="flex gap-1 bg-slate-100 rounded p-1">
              <button
                className={`px-3 py-1 rounded text-sm ${tab === "hospitals" ? "bg-white shadow" : ""}`}
                onClick={() => { setTab("hospitals"); setSelectedHospital(null); }}
              >
                {t("discover.hospitalsTab")}
              </button>
              <button
                className={`px-3 py-1 rounded text-sm ${tab === "doctors" ? "bg-white shadow" : ""}`}
                onClick={() => setTab("doctors")}
                disabled={!selectedHospital}
              >
                {t("discover.doctorsTab")}
              </button>
            </div>
          </div>

          {tab === "hospitals" && (
            <div className="mb-4 h-[400px] rounded-xl border border-slate-200 overflow-hidden">
              <div ref={mapRef} className="w-full h-full" />
            </div>
          )}

          {tab === "hospitals" && (
            <div className="space-y-3">
              {hospitals.loading && <Loading />}
              {hospitals.error != null && <ErrorPanel error={hospitals.error} />}
              {!hospitals.loading && hospitals.data && hospitals.data.length === 0 && (
                <Empty title={String(t("discover.noHospitals"))} />
              )}
              {hospitals.data?.map((hospital) => (
                <Card key={hospital.id} onClick={() => pickHospital(hospital)} className="cursor-pointer hover:shadow-md transition-shadow">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="text-lg font-semibold truncate">{hospital.name}</h3>
                        {hospital.is_simulated && <SimTag />}
                        {hospital.is_approved === false && (
                          <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-800 rounded">
                            {String(t("discover.pendingApproval"))}
                          </span>
                        )}
                      </div>
                      <p className="text-slate-600">{hospital.address || `${hospital.locality}, ${hospital.city}`}</p>
                      {hospital.phone && <p className="text-sm text-slate-500">{hospital.phone}</p>}
                    </div>
                    <div className="text-right">
                      {hospital.distance_km != null && (
                        <p className="text-xl font-bold text-brand-600">{hospital.distance_km.toFixed(1)} km</p>
                      )}
                      <Button variant="secondary" className="mt-2" onClick={(e) => { e.stopPropagation(); pickHospital(hospital); }}>
                        {t("discover.viewDoctors")}
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          {tab === "doctors" && selectedHospital && (
            <>
              <Card className="mb-4">
                <Button variant="quiet" onClick={backToHospitals} className="mb-2">
                  ← {t("discover.backToHospitals")}
                </Button>
                <h3 className="font-semibold">{selectedHospital.name}</h3>
                <p className="text-sm text-slate-600">{selectedHospital.locality}, {selectedHospital.city}</p>
              </Card>

              <div className="mb-4">
                <label className="label">{t("discover.filterSpecialty")}</label>
                <select
                  className="input max-w-xs"
                  value={specialtyId || ""}
                  onChange={(e) => setSpecialtyId(e.target.value || null)}
                >
                  <option value="">{t("discover.allSpecialties")}</option>
                  {specialties.data?.map((s) => (
                    <option key={s.id} value={s.id}>
                      {lang === "te" ? s.name_te : s.name_en}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-3">
                {doctors.loading && <Loading />}
                {doctors.error != null && <ErrorPanel error={doctors.error} />}
                {!doctors.loading && doctors.data && doctors.data.length === 0 && (
                  <Empty title={String(t("discover.noDoctors"))} />
                )}
                {doctors.data?.map((doctor) => (
                  <Card key={doctor.affiliation_id}>
                    <p className="text-xl font-semibold">{doctor.doctor_name}</p>
                    <p className="text-slate-600">
                      {lang === "te" ? doctor.specialty.name_te : doctor.specialty.name_en}
                      {doctor.qualifications && `, ${doctor.qualifications}`}
                    </p>
                    <p className="text-sm text-slate-500">
                      {doctor.hospital.name}, {doctor.hospital.locality}
                    </p>
                    {doctor.consultation_fee !== null && (
                      <p className="text-brand-600 font-medium">{t("book.fee")}: ₹{doctor.consultation_fee}</p>
                    )}
                    {doctor.next_slots.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {doctor.next_slots.slice(0, 3).map((slot) => (
                          <Button
                            key={slot.id}
                            variant="secondary"
                            onClick={() => {
                              navigate(`/book?specialty=${doctor.specialty.id}`);
                            }}
                          >
                            {fmtDateTime(slot.starts_at, lang)}
                          </Button>
                        ))}
                        {doctor.next_slots.length > 3 && (
                          <Button variant="quiet">
                            +{doctor.next_slots.length - 3} more
                          </Button>
                        )}
                      </div>
                    )}
                    {doctor.next_slots.length === 0 && (
                      <p className="mt-3 text-sm text-slate-500">{t("book.noSlots")}</p>
                    )}
                    <Button
                      variant="secondary"
                      className="mt-3"
                      onClick={() => navigate(`/book?specialty=${doctor.specialty.id}`)}
                    >
                      {t("discover.bookWithDoctor")}
                    </Button>
                  </Card>
                ))}
              </div>
            </>
          )}

          {selectedHospital && tab === "doctors" && !canBook && (
            <Banner kind="warning">{t("care.noBookingPermission")}</Banner>
          )}
        </>
      )}
    </div>
  );
}