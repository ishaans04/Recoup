"use client";

import { useEffect, useRef, useState } from "react";

import { injectDemoCase, isApiClientError } from "@/lib/api";
import { DEMO_CONTACT_EMAIL, DEMO_CONTACT_PHONE } from "@/lib/config";

import { GLASS, PILL_BUTTON, PILL_BUTTON_ACCENT } from "./chrome";

/**
 * A one-click trigger for the two recovery channels that reach a real person.
 *
 * The recovery loop already places these calls on its own — an
 * `expired_instrument` failure routes to `customer_nudge`, and the channel
 * policy picks voice, SMS or email from the customer's contact details without
 * anyone pressing anything. What this control supplies is the *failure*, which
 * would otherwise have to be posted from a terminal mid-demo.
 *
 * The contact details live in this browser's local storage, never in the
 * repository and never on the server. Set them once before recording; the
 * buttons are then a single click on camera.
 *
 * The two amounts are not arbitrary. The channel policy leads with voice only
 * at or above ₹5,000 and only with a phone on file, and the constraint gate
 * refuses anything over ₹50,000 outright — so ₹12,990 with a phone takes the
 * voice path, and ₹1,299 with no phone collapses the chain to email alone.
 */

const STORAGE_KEY = "recoup.demo.contact";

const VOICE_AMOUNT_PAISE = 1_299_000; // Rs 12,990 — above the voice threshold
const EMAIL_AMOUNT_PAISE = 129_900; // Rs 1,299 — below it, so no call is placed

/** The expiry rule's exact code, so Tier 1 resolves it without touching the LLM. */
const EXPIRED_CARD = {
  failure_code: "BAD_REQUEST_CARD_EXPIRED",
  failure_message: "Your card has expired.",
  failure_type: "subscription" as const,
  method: "card",
  issuer: "HDFC",
};

interface Contact {
  name: string;
  phone: string;
  email: string;
}

function loadContact(): Contact {
  const fallback: Contact = {
    name: "Demo Customer",
    phone: DEMO_CONTACT_PHONE,
    email: DEMO_CONTACT_EMAIL,
  };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<Contact>;
    return {
      name: parsed.name?.trim() || fallback.name,
      phone: parsed.phone?.trim() ?? fallback.phone,
      email: parsed.email?.trim() ?? fallback.email,
    };
  } catch {
    // A private window, cleared site data, or storage disabled entirely.
    return fallback;
  }
}

export default function LiveNudgeControl({
  disabled,
  onInjected,
}: {
  disabled: boolean;
  onInjected: (txnId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [contact, setContact] = useState<Contact>({
    name: "Demo Customer",
    phone: "",
    email: "",
  });
  const [busy, setBusy] = useState<"voice" | "email" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // Local storage is only readable on the client, so the saved contact is
  // adopted a frame after mount rather than during render — that keeps the
  // server's markup and the client's first paint identical, which matters here
  // because these are controlled inputs.
  useEffect(() => {
    const raf = requestAnimationFrame(() => setContact(loadContact()));
    return () => cancelAnimationFrame(raf);
  }, []);

  // Close on an outside click, so the popover never sits over the console while
  // the operator is trying to read a row behind it.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onPointerDown);
    return () => window.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  function persist(next: Contact) {
    setContact(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage unavailable: the value still works for this session.
    }
  }

  async function fire(kind: "voice" | "email") {
    setNote(null);
    if (kind === "voice" && !contact.phone.trim()) {
      setNote("Add a phone number first — voice and SMS need one.");
      return;
    }
    if (kind === "email" && !contact.email.trim()) {
      setNote("Add an email address first.");
      return;
    }

    setBusy(kind);
    try {
      const response = await injectDemoCase({
        ...EXPIRED_CARD,
        amount_paise: kind === "voice" ? VOICE_AMOUNT_PAISE : EMAIL_AMOUNT_PAISE,
        customer: {
          name: contact.name.trim() || "Demo Customer",
          // Withholding the phone is what collapses the chain to email alone.
          phone: kind === "voice" ? contact.phone.trim() : null,
          email: contact.email.trim() || null,
        },
      });
      onInjected(response.txn_id);
      setNote(
        kind === "voice"
          ? "Injected. The call is placed by the recovery loop — watch the audit stream."
          : "Injected. The email is sent by the recovery loop — watch the audit stream.",
      );
      setOpen(false);
    } catch (error) {
      setNote(
        isApiClientError(error) ? error.message : "Could not inject the nudge case.",
      );
    } finally {
      setBusy(null);
    }
  }

  const fieldStyle = {
    width: "100%",
    padding: "7px 10px",
    borderRadius: 8,
    border: "1px solid rgba(255,255,255,0.14)",
    background: "rgba(0,0,0,0.35)",
    color: "#e9e9f0",
    fontFamily: "var(--font-mono)",
    fontSize: 11.5,
    outline: "none",
  } as const;

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        disabled={disabled}
        aria-expanded={open}
        style={{
          ...PILL_BUTTON,
          padding: "8px 14px",
          fontSize: 11.5,
          opacity: disabled ? 0.45 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
        title={disabled ? "Backend not reachable" : "Trigger a real voice call or email"}
      >
        nudge me ▾
      </button>

      {open && (
        <div
          style={{
            ...GLASS,
            background: "#0d1219",
            backdropFilter: "none",
            WebkitBackdropFilter: "none",
            border: "1px solid rgba(244,63,94,0.2)",
            boxShadow:
              "0 24px 48px -12px rgba(0,0,0,0.7), 0 0 0 1px rgba(244,63,94,0.08)",
            position: "absolute",
            top: "calc(100% + 10px)",
            right: 0,
            zIndex: 40,
            width: 290,
            padding: 16,
            borderRadius: 14,
            display: "grid",
            gap: 10,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "rgba(233,233,240,0.45)",
            }}
          >
            Contact for this demo
          </div>

          <input
            value={contact.name}
            onChange={(event) => persist({ ...contact, name: event.target.value })}
            placeholder="Name"
            aria-label="Customer name"
            style={fieldStyle}
          />
          <input
            value={contact.phone}
            onChange={(event) => persist({ ...contact, phone: event.target.value })}
            placeholder="+91XXXXXXXXXX (Twilio-verified)"
            aria-label="Phone number"
            style={fieldStyle}
          />
          <input
            value={contact.email}
            onChange={(event) => persist({ ...contact, email: event.target.value })}
            placeholder="you@example.com"
            aria-label="Email address"
            style={fieldStyle}
          />

          <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
            <button
              type="button"
              onClick={() => void fire("voice")}
              disabled={busy !== null}
              style={{ ...PILL_BUTTON_ACCENT, flex: 1, textAlign: "center", justifyContent: "center" }}
            >
              {busy === "voice" ? "calling…" : "Voice call"}
            </button>
            <button
              type="button"
              onClick={() => void fire("email")}
              disabled={busy !== null}
              style={{ ...PILL_BUTTON, flex: 1, padding: "8px 14px", fontSize: 11.5 }}
            >
              {busy === "email" ? "sending…" : "Email"}
            </button>
          </div>

          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              lineHeight: 1.6,
              color: "rgba(233,233,240,0.4)",
            }}
          >
            Saved in this browser only. Voice injects ₹12,990 (voice → sms → email);
            Email injects ₹1,299 with no phone, so only email is tried.
          </div>
        </div>
      )}

      {note !== null && (
        <div
          role="status"
          style={{
            position: "absolute",
            top: "calc(100% + 10px)",
            right: 0,
            zIndex: 39,
            maxWidth: 300,
            padding: "8px 12px",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(10,10,16,0.92)",
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            lineHeight: 1.5,
            color: "rgba(233,233,240,0.7)",
            display: open ? "none" : "block",
          }}
        >
          {note}
        </div>
      )}
    </div>
  );
}
