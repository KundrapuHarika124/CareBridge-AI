import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { get, query, type Appointment, type Relationship, type WaitOffer } from "../api";
import { can, useAuth } from "../auth";
import { fmtDateTime } from "../lib/format";
import { Banner, Card, Empty, ErrorPanel, Loading, SimTag, useLang, useLoad } from "../ui";

interface HomeData { next: Appointment | null; offers: WaitOffer[]; pendingRequests: number }

export default function Home() {
  const { t } = useTranslation();
  const lang = useLang();
  const { user, activePatient } = useAuth();
  const canView = can(activePatient, "VIEW_APPOINTMENTS");
  const canBook = can(activePatient, "BOOK_APPOINTMENTS");

  const { data, error, loading, reload } = useLoad<HomeData>(async () => {
    const result: HomeData = { next: null, offers: [], pendingRequests: 0 };
    if (activePatient && canView) {
      const upcoming = await get<Appointment[]>(`/appointments${query({ patient_id: activePatient.id, scope: "upcoming" })}`);
      result.next = upcoming[0] ?? null;
    }
    if (activePatient && canBook) {
      result.offers = (await get<{ offers: WaitOffer[] }>(`/waiting-list${query({ patient_id: activePatient.id })}`)).offers;
    }
    if (user?.role === "PATIENT") {
      const rels = await get<Relationship[]>("/care/relationships");
      result.pendingRequests = rels.filter((r) => r.status === "REQUESTED").length;
    }
    return result;
  }, [activePatient?.id, canView, canBook, user?.role]);

  if (user?.role === "CAREGIVER" && !activePatient) {
    return (
      <Empty title={t("care.choosePatientFirst")}>
        <Link to="/patients" className="btn btn-primary">{t("nav.patients")}</Link>
      </Empty>
    );
  }

  return (
    <div>
      <h1 className="mb-4">{t("home.greeting", { name: user?.full_name ?? "" })}</h1>

      {canBook ? (
        <div className="mb-6 grid gap-3 sm:grid-cols-2">
          <Link to="/assistant" className="btn btn-primary flex-col py-6 text-xl">
            <span aria-hidden="true" className="text-3xl">🎙</span>
            {t("home.talkToAssistant")}
          </Link>
          <Link to="/book" className="btn btn-secondary flex-col py-6 text-xl">
            <span aria-hidden="true" className="text-3xl">📅</span>
            {t("home.bookManually")}
          </Link>
        </div>
      ) : (
        <Banner kind="info">{t("care.noBookingPermission")}</Banner>
      )}

      {loading && <Loading />}
      {error != null && <ErrorPanel error={error} onRetry={reload} />}

      {data && data.pendingRequests > 0 && (
        <Banner kind="warning">
          {t("home.pendingRequests", { count: data.pendingRequests })}{" "}
          <Link to="/care-circle" className="font-semibold underline">{t("home.review")}</Link>
        </Banner>
      )}
      {data && data.offers.length > 0 && (
        <Banner kind="success">
          {t("home.offerWaiting")} <Link to="/appointments" className="font-semibold underline">{t("home.review")}</Link>
        </Banner>
      )}

      {data && canView && (
        <section aria-labelledby="next-title">
          <h2 id="next-title" className="mb-2">{t("home.nextAppointment")}</h2>
          {data.next ? (
            <Card>
              <p className="text-xl font-semibold">{fmtDateTime(data.next.starts_at, lang)}</p>
              <p>{data.next.doctor_name}</p>
              <p>
                {data.next.hospital.name}, {data.next.hospital.locality}
                {data.next.hospital.is_simulated && <SimTag />}
              </p>
              <Link to={`/appointments/${data.next.id}`} className="btn btn-secondary mt-3">{t("appt.details")}</Link>
            </Card>
          ) : (
            <Empty title={t("home.noUpcoming")} />
          )}
        </section>
      )}
    </div>
  );
}
