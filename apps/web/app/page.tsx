"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Spinner } from "@/components/ui";
import { getToken } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(getToken() ? "/cases" : "/login");
  }, [router]);

  return <Spinner label="正在进入工作台…" />;
}