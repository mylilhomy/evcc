<template>
	<div class="mode-group border d-inline-flex" role="group" data-testid="mode">
		<button
			type="button"
			class="btn flex-grow-1 flex-shrink-1 text-truncate-xs-only"
			:class="{ active: manual }"
			tabindex="0"
			@click="$emit('updated', true)"
		>
			{{ $t("main.mode.manual") }}
		</button>
		<button
			type="button"
			class="btn flex-grow-1 flex-shrink-1 text-truncate-xs-only"
			:class="{ active: !manual }"
			tabindex="0"
			@click="$emit('updated', false)"
		>
			{{ $t("main.mode.auto") }}
		</button>
	</div>
</template>

<script lang="ts">
import { defineComponent } from "vue";

export default defineComponent({
	name: "Mode",
	props: {
		manual: Boolean,
	},
	emits: ["updated"],
});
</script>

<style scoped>
.mode-group {
	border: 2px solid var(--evcc-default-text);
	border-radius: 20px;
	padding: 4px;
	min-width: 255px;
}

.btn {
	/* equal width buttons */
	flex-basis: 0;
	white-space: nowrap;
	border-radius: 18px;
	padding: 0.1em 0.8em;
	color: var(--evcc-default-text);
	border: none;
}
@media (max-width: 576px) {
	.btn {
		padding: 0.1em 0.2em;
	}
}

.btn:hover {
	color: var(--evcc-gray);
}
.btn:focus {
	outline: var(--bs-focus-ring-width) solid var(--bs-focus-ring-color);
	outline-width: var(--bs-focus-ring-width);
}
.btn.active {
	color: var(--evcc-background);
	background: var(--evcc-default-text);
}
.btn-group {
	border-radius: 16px;
}
</style>
