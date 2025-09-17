const { Client } = require('@anthropic-ai/sdk');
const axios = require('axios');
const fs = require('fs');

class ElevenLabsCalendarIntegration {
  constructor(elevenLabsApiKey, anthropicApiKey) {
    this.elevenLabsApiKey = elevenLabsApiKey;
    this.anthropic = new Client({ apiKey: anthropicApiKey });
  }

  async convertCalendarEventToSpeech(eventText, voiceId = 'pNInz6obpgDQGcFmaJgB') {
    try {
      const response = await axios.post(
        `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
        {
          text: eventText,
          model_id: 'eleven_monolingual_v1',
          voice_settings: {
            stability: 0.5,
            similarity_boost: 0.5
          }
        },
        {
          headers: {
            'Accept': 'audio/mpeg',
            'Content-Type': 'application/json',
            'xi-api-key': this.elevenLabsApiKey
          },
          responseType: 'arraybuffer'
        }
      );

      return response.data;
    } catch (error) {
      console.error('Error converting text to speech:', error);
      throw error;
    }
  }

  async saveAudio(audioBuffer, filename) {
    fs.writeFileSync(filename, audioBuffer);
    console.log(`Audio saved as ${filename}`);
  }
}

module.exports = ElevenLabsCalendarIntegration;
