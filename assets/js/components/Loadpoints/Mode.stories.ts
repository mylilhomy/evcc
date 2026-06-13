import Mode from "./Mode.vue";
import type { Meta, StoryFn } from "@storybook/vue3";

export default {
  title: "Loadpoints/Mode",
  component: Mode,
  argTypes: {
    manual: { control: "boolean", description: "Manual mode active (vs. automatic)" },
  },
  parameters: {
    layout: "centered",
  },
} as Meta<typeof Mode>;

const Template: StoryFn<typeof Mode> = (args) => {
  const story = () => ({
    components: { Mode },
    setup() {
      return { args };
    },
    template: '<Mode v-bind="args" />',
  });
  story.args = args;
  return story;
};

export const Automatic = Template.bind({});
Automatic.args = { manual: false };

export const Manual = Template.bind({});
Manual.args = { manual: true };
