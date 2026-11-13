# Quellen und Abgrenzung

Recherchiert am 4. November 2026. Herstellerunterlagen sind die maßgebliche Quelle, nicht eine angenommene STM32-Kompatibilität.

- AT32F403A/407 Reference Manual, **V2.07**: https://www.arterychip.com/download/RM/RM_AT32F403A_407_V2.07_EN.pdf
- Frühere zum Registerabgleich verwendete Fassung **V2.06**: https://www.arterychip.com/download/RM/RM_AT32F403A_407_EN_V2.06.pdf
- Hersteller-Firmwarebibliothek: https://github.com/ArteryTek/AT32F403A_407_Firmware_Library
- CMSIS-Geräteheader: https://github.com/ArteryTek/AT32F403A_407_CMSIS_Driver/blob/main/at32f403a_407.h
- Renode: https://github.com/renode/renode
- Renode-Peripheriemodelle: https://github.com/renode/renode-infrastructure

Die exakte SDK-Revision und Hersteller-Datenblattquelle stehen unten. Das Paket enthält keine Kopie der proprietären Benutzerfirmware und keine Hersteller-PDFs. Die neu geschriebenen Modell-/Testdateien stehen unter MIT. Renode und seine mitgelieferten Modelle bleiben unter ihren jeweiligen Lizenzen; das Paket referenziert sie über die installierte Laufzeit.

Übernommen wird Renodes vorhandene Implementierung von CPU/NVIC/SysTick, MappedMemory, BitBanding und STM32_Timer, ohne deren Quellcode im Paket zu duplizieren. Eigene AT32-Modelle ersetzen die inkompatiblen beziehungsweise zu groben RCC/GPIO/UART/DMA-Annahmen. AT32F403A ist kein STM32F4-Drop-in.
29f8bfd95b190fa38070d2e0fbbb9f3871b0b3f5

- Datenblatt **V2.04**: https://www.arterychip.com/download/DS/DS_AT32F403A_V2.04_EN.pdf
- Produktfamilie: https://www.arterychip.com/en/product/AT32F403A.jsp
