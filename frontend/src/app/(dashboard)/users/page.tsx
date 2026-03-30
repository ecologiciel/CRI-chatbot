"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { AdminsTable } from "./components/admins-table";
import { WhitelistSection } from "./components/whitelist-section";
import { InviteDialog } from "./components/invite-dialog";
import { useAdmins } from "@/hooks/use-users";

const MAX_ADMINS = 10;

export default function UsersPage() {
  const [inviteOpen, setInviteOpen] = useState(false);
  const { data } = useAdmins({ page: 1, page_size: 1 });
  const totalAdmins = data?.total ?? 0;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading text-foreground">
            Utilisateurs & Accès
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Gérez les administrateurs et la liste blanche de l&apos;agent
            interne
          </p>
        </div>
        <Button
          onClick={() => setInviteOpen(true)}
          disabled={totalAdmins >= MAX_ADMINS}
        >
          <UserPlus className="h-4 w-4 me-2" strokeWidth={1.75} />
          Inviter un admin
        </Button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="admins">
        <TabsList>
          <TabsTrigger value="admins">Administrateurs</TabsTrigger>
          <TabsTrigger value="whitelist">Liste blanche</TabsTrigger>
        </TabsList>

        <TabsContent value="admins" className="mt-4">
          <AdminsTable />
        </TabsContent>

        <TabsContent value="whitelist" className="mt-4">
          <WhitelistSection />
        </TabsContent>
      </Tabs>

      {/* Invite dialog */}
      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} />
    </div>
  );
}
