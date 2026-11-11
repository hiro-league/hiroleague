// The admin's side menu for the shared UI kit: its groups and their pages, made from the one list of pages
// (lib/shell/nav.ts). How a menu works and who gets what of it: $kit/components/menu.
import type { Component } from 'svelte';
import type { MenuPage } from '$kit/components/menu';
import {
  Activity,
  BookOpen,
  Brain,
  Cpu,
  Database,
  FlaskConical,
  Grid2X2,
  Image,
  KeyRound,
  List,
  MessageSquare,
  Puzzle,
  Server,
  Settings,
  User,
  Users,
  Workflow
} from '@lucide/svelte';
import { navItems } from '$lib/shell/nav';

// nav.ts names its icons in words (it is read by tests and other tools); here they become pictures.
const ICONS: Record<string, Component> = {
  activity: Activity,
  book: BookOpen,
  brain: Brain,
  cpu: Cpu,
  database: Database,
  flask: FlaskConical,
  grid: Grid2X2,
  image: Image,
  key: KeyRound,
  list: List,
  message: MessageSquare,
  puzzle: Puzzle,
  server: Server,
  settings: Settings,
  user: User,
  users: Users,
  workflow: Workflow
};

export const MENU_PAGES: Record<string, MenuPage> = Object.fromEntries(
  navItems.map((item) => [item.path, { route: item.path, title: item.label, icon: ICONS[item.icon] ?? Grid2X2 }])
);

// The groups in menu order, as nav.ts lists them.
const GROUP_ORDER = ['Core', 'Communication', 'Operations', 'Configuration'] as const;

export const MENU_GROUPS: { id: string; title: string; pages: string[] }[] = GROUP_ORDER.map((group) => ({
  id: group.toLowerCase(),
  title: group,
  pages: navItems.filter((item) => item.group === group).map((item) => item.path)
}));
