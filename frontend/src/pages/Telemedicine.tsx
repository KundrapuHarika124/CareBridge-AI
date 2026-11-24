
import { useState } from "react";
import { useAuth } from "../auth";
import { Banner, Button, Card, PageTitle } from "../ui";

export default function Telemedicine() {
  const { user } = useAuth();
  const [roomOpen, setRoomOpen] = useState(false);

  const isDoctor = user?.role === "DOCTOR";

  return (
    <div className="space-y-5">
      <PageTitle>Telemedicine</PageTitle>

      <Banner kind="info">
        Prototype preview only. Live audio and video consultations are
        planned for a future release.
      </Banner>

      {!roomOpen ? (
        <>
          <section className="rounded-2xl bg-gradient-to-r from-sky-900 to-blue-700 p-6 text-white">
            <p className="mb-2 text-sm font-semibold uppercase tracking-wider text-sky-200">
              CareBridge AI · Virtual Care
            </p>
            <h2 className="mb-2 text-2xl font-bold">
              {isDoctor ? "Your virtual clinic" : "Healthcare, beyond boundaries"}
            </h2>
            <p className="max-w-2xl text-sky-100">
              {isDoctor
                ? "A dedicated space for your future online consultations and remote patient care."
                : "Connect with healthcare professionals remotely through secure online consultations."}
            </p>
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-sky-800">
                  CONSULTATION SPACE
                </span>
                <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">
                  Demo preview
                </span>
              </div>

              <h3 className="mb-2 text-xl font-bold">
                {isDoctor ? "Virtual consultation room" : "Online doctor consultation"}
              </h3>

              <p className="mb-4 text-sm text-slate-600">
                {isDoctor
                  ? "Your online consultation workspace will appear here when virtual appointments become available."
                  : "Your online consultation details and joining options will appear here when this feature is enabled."}
              </p>

              <div className="space-y-3 rounded-xl bg-slate-50 p-4">
                <div>
                  <p className="text-xs text-slate-500">CONSULTATION TYPE</p>
                  <p className="font-semibold">Remote video consultation</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">PARTICIPANT</p>
                  <p className="font-semibold">
                    {user?.full_name ?? (isDoctor ? "Doctor" : "Patient")}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">AVAILABILITY</p>
                  <p className="font-semibold text-amber-700">
                    Coming soon
                  </p>
                </div>
              </div>

              <Button className="mt-4 w-full" onClick={() => setRoomOpen(true)}>
                Preview consultation room
              </Button>
            </Card>

            <Card>
              <h3 className="mb-3 text-xl font-bold">Why Telemedicine?</h3>
              <div className="space-y-4">
                <div>
                  <p className="font-semibold">Remote access to care</p>
                  <p className="text-sm text-slate-600">
                    Reduce unnecessary travel for suitable consultations.
                  </p>
                </div>
                <div>
                  <p className="font-semibold">Convenient follow-ups</p>
                  <p className="text-sm text-slate-600">
                    Make future follow-up visits easier to access.
                  </p>
                </div>
                <div>
                  <p className="font-semibold">Connected healthcare</p>
                  <p className="text-sm text-slate-600">
                    Bring patients and doctors together through digital care.
                  </p>
                </div>
              </div>
            </Card>
          </div>
        </>
      ) : (
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-bold">Virtual consultation room</h2>
              <p className="text-sm text-slate-500">Interactive UI preview · No live call</p>
            </div>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900">
              Preview mode
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex min-h-64 flex-col items-center justify-center rounded-xl bg-slate-900 p-6 text-center text-white">
              <div className="mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-sky-800 text-3xl font-bold">
                {user?.full_name?.charAt(0)?.toUpperCase() ?? "U"}
              </div>
              <p className="font-semibold">{user?.full_name ?? "You"}</p>
              <p className="mt-1 text-sm text-slate-300">Your video preview</p>
              <span className="mt-3 rounded-full bg-slate-700 px-3 py-1 text-xs">
                Camera not connected
              </span>
            </div>

            <div className="flex min-h-64 flex-col items-center justify-center rounded-xl bg-slate-100 p-6 text-center">
              <div className="mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-slate-300 text-3xl text-slate-600">
                +
              </div>
              <p className="font-semibold">
                {isDoctor ? "Patient" : "Doctor"}
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Participant video will appear here
              </p>
              <span className="mt-3 rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-900">
                Waiting for live integration
              </span>
            </div>
          </div>

          <Banner kind="warning">
            Camera, microphone, and real-time communication are not connected
            in this prototype.
          </Banner>

          <div className="flex flex-wrap justify-center gap-3">
            <Button variant="secondary" disabled>
              Microphone unavailable
            </Button>
            <Button variant="secondary" disabled>
              Camera unavailable
            </Button>
            <Button variant="danger" onClick={() => setRoomOpen(false)}>
              Exit preview
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
