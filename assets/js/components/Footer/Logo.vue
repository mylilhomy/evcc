<template>
	<svg
		viewBox="0 0 150 35"
		xmlns="http://www.w3.org/2000/svg"
		fill-rule="evenodd"
		clip-rule="evenodd"
		stroke-linejoin="round"
		stroke-miterlimit="2"
	>
		<text
			x="0"
			y="27"
			class="letter"
			font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
			font-size="29"
			font-weight="700"
			letter-spacing="-1"
		>
			inergia
		</text>
	</svg>
</template>

<script lang="ts">
import { defineComponent } from "vue";

export default defineComponent({
	name: "Logo",
});
</script>
<style scoped>
.letter {
	fill: #1c2445;
}
html.dark .letter {
	fill: var(--bs-white);
}
</style>
