<script lang="ts">
  import ChatChannelsPage from '$lib/features/chat-channels/ChatChannelsPage.svelte';
  import AdminShell from '$lib/shell/AdminShell.svelte';
</script>

<AdminShell activePath="chats">
  <ChatChannelsPage />
</AdminShell>
