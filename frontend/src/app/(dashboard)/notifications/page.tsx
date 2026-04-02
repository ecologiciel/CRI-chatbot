"use client";

import { useState } from "react";
import { Bell, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NotificationStats } from "./components/notification-stats";
import { NotificationTable } from "./components/notification-table";
import { SendNotificationDialog } from "./components/send-notification-dialog";
import { TemplateConfig } from "./components/template-config";

export default function NotificationsPage() {
  const [sendDialogOpen, setSendDialogOpen] = useState(false);
  const [periodDays, setPeriodDays] = useState(30);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Notifications</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Historique et gestion des notifications WhatsApp
          </p>
        </div>
        <Button onClick={() => setSendDialogOpen(true)}>
          <Send className="h-4 w-4 me-2" strokeWidth={1.75} />
          Envoyer une notification
        </Button>
      </div>

      {/* KPI Stats */}
      <NotificationStats days={periodDays} onPeriodChange={setPeriodDays} />

      {/* Tabs: History & Templates */}
      <Tabs defaultValue="history">
        <TabsList>
          <TabsTrigger value="history">
            <Bell className="h-4 w-4 me-2" strokeWidth={1.75} />
            Historique
          </TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
        </TabsList>

        <TabsContent value="history" className="mt-4">
          <NotificationTable />
        </TabsContent>

        <TabsContent value="templates" className="mt-4">
          <TemplateConfig />
        </TabsContent>
      </Tabs>

      {/* Send dialog */}
      <SendNotificationDialog
        open={sendDialogOpen}
        onOpenChange={setSendDialogOpen}
      />
    </div>
  );
}
