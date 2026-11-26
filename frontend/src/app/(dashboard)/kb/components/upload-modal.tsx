"use client";

import { useState, useCallback } from "react";
import { Upload, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDocumentCategories, useUploadDocument } from "@/hooks/use-documents";

interface UploadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UploadModal({ open, onOpenChange }: UploadModalProps) {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [language, setLanguage] = useState("");
  const [sourceAuthority, setSourceAuthority] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [sourceVersion, setSourceVersion] = useState("");
  const [publishedAt, setPublishedAt] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");

  const uploadMutation = useUploadDocument();
  const { data: categories = [] } = useDocumentCategories();

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile) {
        setFile(droppedFile);
        if (!title) setTitle(droppedFile.name.replace(/\.[^.]+$/, ""));
      }
    },
    [title],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0];
      if (selectedFile) {
        setFile(selectedFile);
        if (!title) setTitle(selectedFile.name.replace(/\.[^.]+$/, ""));
      }
    },
    [title],
  );

  const resetForm = () => {
    setFile(null);
    setTitle("");
    setCategory("");
    setLanguage("");
    setSourceAuthority("");
    setSourceReference("");
    setSourceVersion("");
    setPublishedAt("");
    setSourceUrl("");
  };

  const handleSubmit = () => {
    if (!file || !title) return;

    uploadMutation.mutate(
      {
        file,
        title,
        category: category.trim() || undefined,
        language: language || undefined,
        source_authority: sourceAuthority || undefined,
        source_reference: sourceReference || undefined,
        source_version: sourceVersion || undefined,
        published_at: publishedAt || undefined,
        source_url: sourceUrl || undefined,
      },
      {
        onSuccess: () => {
          toast.success("Document importé", {
            description: `"${title}" attend une validation avant indexation.`,
          });
          resetForm();
          onOpenChange(false);
        },
        onError: () => {
          toast.error("Erreur lors de l'import", {
            description: "Vérifiez le format et la taille du fichier.",
          });
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) resetForm();
        onOpenChange(value);
      }}
    >
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="font-heading">
            Ajouter un document
          </DialogTitle>
          <DialogDescription>
            Importez un document, puis validez sa source avant son indexation.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Drop zone */}
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            className={cn(
              "relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors",
              dragActive
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/50",
              file &&
                "border-[hsl(var(--success))] bg-[hsl(var(--success))]/5",
            )}
          >
            {file ? (
              <>
                <FileText className="h-8 w-8 text-[hsl(var(--success))] mb-2" />
                <p className="text-sm font-medium">{file.name}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {(file.size / 1_048_576).toFixed(1)} Mo
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2 text-xs"
                  onClick={() => setFile(null)}
                >
                  Changer de fichier
                </Button>
              </>
            ) : (
              <>
                <Upload className="h-8 w-8 text-muted-foreground mb-2" />
                <p className="text-sm font-medium">
                  Glissez un fichier ou{" "}
                  <label className="text-primary cursor-pointer hover:underline">
                    cliquez pour parcourir
                    <input
                      type="file"
                      className="sr-only"
                      accept=".pdf,.docx,.txt,.md,.csv"
                      onChange={handleFileSelect}
                    />
                  </label>
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  PDF, DOCX, TXT, MD, CSV — max 50 Mo
                </p>
              </>
            )}
          </div>

          {file?.name.toLowerCase().endsWith(".csv") && (
            <p className="text-sm text-muted-foreground">
              Pour un CSV, la première ligne est supposée contenir les intitulés des colonnes. Vérifiez-la avant l&apos;import.
            </p>
          )}

          <div className="space-y-2 rounded-md border p-3">
            <p className="text-sm font-medium">Preuve et validité de la source <span className="text-destructive">*</span></p>
            <div className="grid grid-cols-2 gap-3">
              <Input required placeholder="Organisme émetteur" value={sourceAuthority} onChange={(e) => setSourceAuthority(e.target.value)} />
              <Input required placeholder="Référence officielle" value={sourceReference} onChange={(e) => setSourceReference(e.target.value)} />
              <Input required placeholder="Version" value={sourceVersion} onChange={(e) => setSourceVersion(e.target.value)} />
              <label className="text-sm">Date de publication (si connue)<Input type="date" value={publishedAt} onChange={(e) => setPublishedAt(e.target.value)} aria-label="Date de publication si connue" /></label>
            </div>
            <Input type="url" placeholder="Lien officiel (optionnel)" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
          </div>

          {/* Title */}
          <div className="space-y-2">
            <Label htmlFor="doc-title">Titre</Label>
            <Input
              id="doc-title"
              placeholder="Titre du document"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          {/* Category + Language */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="document-category">Catégorie</Label>
              <Input id="document-category" list="existing-document-categories" maxLength={100}
                placeholder="Ex. Santé végétale" value={category}
                onChange={(event) => setCategory(event.target.value)} />
              <datalist id="existing-document-categories">
                {categories.map((item) => <option key={item} value={item} />)}
              </datalist>
            </div>
            <div className="space-y-2">
              <Label>Langue</Label>
              <Select value={language} onValueChange={setLanguage}>
                <SelectTrigger>
                  <SelectValue placeholder="Sélectionner" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fr">Français</SelectItem>
                  <SelectItem value="ar">Arabe</SelectItem>
                  <SelectItem value="en">Anglais</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Annuler
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!file || !title || !sourceAuthority || !sourceReference || !sourceVersion || !publishedAt || uploadMutation.isPending}
          >
            {uploadMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 me-2 animate-spin" />
                Import en cours...
              </>
            ) : (
              "Importer"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
