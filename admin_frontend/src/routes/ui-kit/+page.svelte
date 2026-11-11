<script lang="ts">
  // The shared UI kit's gallery, shown as the admin has it: the pieces, the Theme designer and the standard pages.
  import Gallery from '$kit/gallery/gallery.svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
</script>

<PageHeader
  title="UI kit"
  description="The shared UI kit every Hiro app is built from, shown as deployed in this admin. The Theme tab designs a theme and copies it to an app."
/>

<Gallery />
